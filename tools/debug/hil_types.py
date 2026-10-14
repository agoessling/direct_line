"""Host-side types for the firmware's test table and execution reports."""

from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict


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
