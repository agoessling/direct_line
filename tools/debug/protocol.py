"""Firmware test records and shared host-side result validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict, cast


class Case(TypedDict):
    id: int
    name: str
    timeout_ms: int
    expected: int


class SelectedCase(Case):
    token: int


class CaseResult(SelectedCase):
    passed: bool
    error: str | None
    observation: dict[str, object]


class RunResult(TypedDict):
    duration_s: float
    identity: dict[str, str]
    cases: list[CaseResult]
    process_exit_code: int | None
    debugger_error: str | None
    passed: bool


class BoardResult(TypedDict):
    probe: str
    elf_sha256: str
    tools: dict[str, str]
    passed: bool
    duration_s: NotRequired[float]
    identity: NotRequired[dict[str, str]]
    cases: NotRequired[list[CaseResult]]
    process_exit_code: NotRequired[int | None]
    debugger_error: NotRequired[str | None]
    error: NotRequired[str]


@dataclass(frozen=True)
class RunConfig:
    probe: str
    elf: Path
    dslite: Path
    ccs_worker: Path


class DebugRequest(TypedDict):
    config: str
    elf: str
    report: str
    cases: list[SelectedCase]
    ready: int
    done: int
    request: int
    result: int
    diagnostic: int
    failure: int


def words(value: object) -> list[int]:
    """Decode unsigned target words from a debugger report."""
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for word in cast(list[object], value):
        if not isinstance(word, (int, float)) or not 0 <= word <= 0xFFFFFFFF or word != int(word):
            return []
        result.append(int(word))
    return result


def address_equal(actual: object, expected: int) -> bool:
    """Compare instruction addresses with the Thumb bit cleared."""
    return (
        isinstance(actual, (int, float))
        and 0 <= actual <= 0xFFFFFFFF
        and actual == int(actual)
        and int(actual) & ~1 == expected & ~1
    )


def evaluate(case: SelectedCase, observation: dict[str, object], done: int) -> str | None:
    """Require a fresh matching result before interpreting any terminal state."""
    if observation.get("error"):
        return str(observation["error"])
    result = words(observation.get("result"))
    diagnostic = words(observation.get("diagnostic"))
    if len(result) != 4 or result[:3] != [1, case["id"], case["token"]]:
        return "Missing or stale case result"
    if len(diagnostic) != 7 or diagnostic[0] != 0x444C5253:
        return "Invalid boot diagnostic"
    status, stage = result[3], diagnostic[1]
    expected = case["expected"]
    if expected == 0:
        valid = (
            status == 2
            and stage == 2
            and not observation.get("timed_out", True)
            and address_equal(observation.get("pc"), done)
        )
    elif expected == 1:
        valid = status == 1 and stage == 0xFFFF0002
    elif expected == 2:
        valid = status == 1 and stage == 0xFFFF0001 and diagnostic[2:5] == [6, 1 << 16, 0]
    else:
        valid = status == 1 and stage == 2 and observation.get("timed_out") is True
    return None if valid else f"Unexpected terminal state: {observation}"
