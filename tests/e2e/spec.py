from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SeedFile:
    """A file written into the temp project before the claude session runs."""

    path: str               # relative to the temp workdir
    content: str
    executable: bool = False


@dataclass
class ScenarioSpec:
    """A single real-world scenario: a prompt + expectations about the emitted crate."""

    name: str
    area: str               # profiles|fields|admin|enforced|recovery|privacy|natural
    prompt: str
    expected_profile_uri: Optional[str] = None     # None => only assert validity
    model: str = "sonnet"
    seed_files: tuple[SeedFile, ...] = ()
    git_init: bool = True
    git_commit: bool = True
    timeout: int = 360
    public: bool = False
    strict: bool = False
    expect_validation_status: tuple[str, ...] = ("passed", "warning")
    allow_blocked: bool = False                      # enforced scenarios
    needles: tuple[str, ...] = ()                    # must NOT appear in a public crate
    coverage_tags: frozenset[str] = field(default_factory=frozenset)
    # extra per-scenario assertions: check(graph, result) -> None, raises on failure
    check: Optional[Callable[[list, ScenarioResult], None]] = None
    append_system_prompt: Optional[str] = None


@dataclass
class ScenarioResult:
    """The outcome of running a scenario: the emitted crate plus validation output."""

    spec: ScenarioSpec
    workdir: Path
    crate_path: Optional[Path]
    graph: Optional[list]
    transcript: str
    validate_json: Optional[dict]
    status_json: Optional[dict]
    claude_exit: int
