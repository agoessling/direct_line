"""Firmware test records and shared host-side result validation."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Self, TypedDict, cast

# Shared ABI: firmware/hil_test.rs and firmware/hil_registry.rs. Keep values in sync.
PROTOCOL_VERSION = 1
WORD_BITS = 32
WORD_BYTES = WORD_BITS // 8
U32_MAX = (1 << WORD_BITS) - 1
INVALID_CASE_ID = U32_MAX
NO_TOKEN = 0
REQUEST_WORDS = 2
RESULT_WORDS = 4


class ExpectedOutcome(IntEnum):
    PASS = 0
    PANIC = 1
    FAULT = 2  # UDF UsageFault.
    TIMEOUT = 3


class Status(IntEnum):
    IDLE = 0
    RUNNING = 1
    PASS = 2


# Shared boot diagnostic ABI: firmware/startup.rs.
BOOT_DIAGNOSTIC_MAGIC = 0x444C5253  # "DLRS", written by startup.
BOOT_DIAGNOSTIC_WORDS = 7


class BootStage(IntEnum):
    RESET = 0
    TRIM = 1
    APPLICATION = 2
    FAULT = 0xFFFF0001
    PANIC = 0xFFFF0002


# Arm Cortex-M exception numbering and Configurable Fault Status Register bits.
USAGE_FAULT_EXCEPTION = 6
CFSR_UNDEFINSTR = 1 << 16
THUMB_BIT = 1


@dataclass(frozen=True)
class Result:
    version: int
    case_id: int
    token: int
    status: Status

    @classmethod
    def from_words(cls, value: object) -> Self:
        version, case_id, token, status = words(value, RESULT_WORDS)
        if version != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported HIL protocol version: {version}")
        return cls(version, case_id, token, Status(status))


@dataclass(frozen=True)
class FaultDetails:
    exception: int
    cfsr: int
    hfsr: int
    mmfar: int
    bfar: int


@dataclass(frozen=True)
class PanicDetails:
    line: int
    column: int
    filename_address: int
    filename_length: int
    reserved: int


@dataclass(frozen=True)
class BootDiagnostic:
    stage: BootStage
    details: FaultDetails | PanicDetails | None

    @classmethod
    def from_words(cls, value: object) -> Self:
        magic, raw_stage, *payload = words(value, BOOT_DIAGNOSTIC_WORDS)
        if magic != BOOT_DIAGNOSTIC_MAGIC:
            raise ValueError("Invalid boot diagnostic magic")
        stage = BootStage(raw_stage)
        details: FaultDetails | PanicDetails | None = None
        if stage == BootStage.FAULT:
            details = FaultDetails(*payload)
        elif stage == BootStage.PANIC:
            details = PanicDetails(*payload)
        elif any(payload):
            raise ValueError("Unexpected boot diagnostic payload before fault/panic")
        return cls(stage, details)


class Case(TypedDict):
    id: int
    name: str
    timeout_ms: int
    expected: int
    suites: list[str]


class SelectedCase(Case):
    token: int


@dataclass
class CaseResult:
    case: SelectedCase
    passed: bool
    error: str | None
    observation: dict[str, object]


@dataclass
class RunResult:
    duration_s: float
    identity: dict[str, str]
    cases: list[CaseResult]
    process_exit_code: int | None
    debugger_error: str | None
    passed: bool


@dataclass
class BoardResult:
    probe: str
    elf_sha256: str
    tools: dict[str, str]
    run: RunResult | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.run is not None and self.run.passed


@dataclass(frozen=True)
class RunConfig:
    probe: str
    elf: Path
    dslite: Path
    ccs_worker: Path


class DebugRequest(TypedDict):
    probe: str
    config: str
    elf: str
    report: str
    cases: list[SelectedCase]
    ready: int
    done: int
    request: int
    result: int
    diagnostic: int


def words(value: object, count: int) -> list[int]:
    """Validate a fixed-size record of unsigned words; CCS may return integral JSON doubles."""
    if not isinstance(value, list):
        raise ValueError(f"Expected {count} target words")
    raw = cast(list[object], value)
    if len(raw) != count:
        raise ValueError(f"Expected {count} target words")
    result: list[int] = []
    for word in raw:
        if (
            isinstance(word, bool)
            or not isinstance(word, (int, float))
            or not 0 <= word <= U32_MAX
            or word != int(word)
        ):
            raise ValueError("Invalid unsigned target word")
        result.append(int(word))
    return result


def address_equal(actual: object, expected: int) -> bool:
    """Compare instruction addresses with the Thumb bit cleared."""
    return (
        not isinstance(actual, bool)
        and isinstance(actual, (int, float))
        and 0 <= actual <= U32_MAX
        and actual == int(actual)
        and int(actual) & ~THUMB_BIT == expected & ~THUMB_BIT
    )


def evaluate(case: SelectedCase, observation: Mapping[str, object], done: int) -> str | None:
    """Require a fresh matching result before interpreting any terminal state."""
    if observation.get("error"):
        return str(observation["error"])
    try:
        result = Result.from_words(observation.get("result"))
    except ValueError as error:
        return f"Invalid case result: {error}"
    if result.case_id != case["id"] or result.token != case["token"] or result.token == NO_TOKEN:
        return "Missing or stale case result"
    try:
        diagnostic = BootDiagnostic.from_words(observation.get("diagnostic"))
    except ValueError as error:
        return f"Invalid boot diagnostic: {error}"
    expected = case["expected"]
    if expected == ExpectedOutcome.PASS:
        valid = (
            result.status == Status.PASS
            and diagnostic.stage == BootStage.APPLICATION
            and observation.get("timed_out") is False
            and address_equal(observation.get("pc"), done)
        )
    elif expected == ExpectedOutcome.PANIC:
        valid = result.status == Status.RUNNING and diagnostic.stage == BootStage.PANIC
    elif expected == ExpectedOutcome.FAULT:
        fault = diagnostic.details
        valid = (
            result.status == Status.RUNNING
            and diagnostic.stage == BootStage.FAULT
            and isinstance(fault, FaultDetails)
            and fault.exception == USAGE_FAULT_EXCEPTION
            and fault.cfsr == CFSR_UNDEFINSTR
            and fault.hfsr == 0
        )
    elif expected == ExpectedOutcome.TIMEOUT:
        valid = (
            result.status == Status.RUNNING
            and diagnostic.stage == BootStage.APPLICATION
            and observation.get("timed_out") is True
        )
    else:
        return f"Unknown expected outcome: {expected}"
    return None if valid else f"Unexpected terminal state: {observation}"
