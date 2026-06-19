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
    # Skip the standard crate battery and run only `check` (for recovery / blocked-export
    # scenarios that assert journal state rather than a finished, valid crate).
    skip_crate_battery: bool = False
    needles: tuple[str, ...] = ()                    # must NOT appear in a public crate
    env: Optional[dict] = None                       # extra env vars for the claude session
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
    # True if the agent edited the per-scenario source snapshot that actually ran
    # (the code under test). A local, per-scenario integrity signal — unlike the global
    # repo-dirty check it cannot be tripped by a *different* scenario's tampering.
    source_tampered: bool = False
