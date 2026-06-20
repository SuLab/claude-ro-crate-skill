"""Hand-(de)serialized config, state, event, and projection dataclasses.

These dataclasses are the in-memory shapes for ``config.json``, ``state.json``,
journal events, and the reduced ``RunModel`` consumed by crate assembly. They are
serialized and parsed by hand in ``state.py`` rather than via a schema library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

JsonDict = dict[str, Any]


@dataclass
class PrivacyConfig:
    include_prompts: bool = False
    include_event_journal: bool = False
    include_full_logs: bool = False
    include_source_code_public: bool = False
    include_git_diff_public: bool = False
    public_by_default: bool = False


@dataclass
class FilePolicy:
    include_declared_inputs: bool = False
    include_declared_outputs: bool = True
    include_logs: str = "safe-and-size-limited"
    include_source_code: str = "private-only"
    include_git_diff: str = "private-only"
    include_event_journal: bool = False
    max_log_size_mb: int = 10
    max_file_size_mb: int = 100


@dataclass
class HashPolicy:
    max_file_size_mb: int = 100
    hash_large_files: bool = False


@dataclass
class RedactionConfig:
    enabled: bool = True
    patterns_file: str = ".ro-crate-run/secrets-redaction.json"
    environment_allowlist: list[str] = field(
        default_factory=lambda: [
            "PATH",
            "LANG",
            "LC_ALL",
            "SHELL",
            "PYTHONPATH",
            "CONDA_DEFAULT_ENV",
            "VIRTUAL_ENV",
        ]
    )


@dataclass
class ValidationConfig:
    strict: bool = False
    require_git_commit: bool = False
    require_clean_git: bool = False
    require_declared_outputs: bool = True
    require_software_versions: bool = True
    require_date_published: bool = True
    require_privacy_gate: bool = True


@dataclass
class RemoteJournalConfig:
    enabled: bool = False
    type: str = "http"
    endpoint: Optional[str] = None
    timeout_seconds: int = 5
    fail_closed: bool = False


@dataclass
class RcrConfig:
    schema_version: str = "1.0.0"
    mode: str = "monitored"
    default_profile: str = "process"
    project_name: Optional[str] = None
    crate_name: Optional[str] = None
    copy_mode: str = "mixed"
    output_roots: list[str] = field(default_factory=lambda: ["results", "outputs", "reports"])
    source_roots: list[str] = field(
        default_factory=lambda: ["src", "scripts", "workflow", "workflows"]
    )
    ignore_patterns: list[str] = field(
        default_factory=lambda: [
            ".git/**",
            "node_modules/**",
            ".venv/**",
            "venv/**",
            "__pycache__/**",
            ".mypy_cache/**",
            ".pytest_cache/**",
            ".ro-crate-run/**",
        ]
    )
    hash_policy: HashPolicy = field(default_factory=HashPolicy)
    file_policy: FilePolicy = field(default_factory=FilePolicy)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    redaction: RedactionConfig = field(default_factory=RedactionConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    remote_journal: RemoteJournalConfig = field(default_factory=RemoteJournalConfig)
    profile_uri: str = ""


@dataclass
class LastCheckpoint:
    event_id: str
    timestamp: str
    event_sequence: int
    materialized_through_sequence: int
    validation_status: str
    materializer_version: Optional[str] = None


@dataclass
class RcrState:
    run_id: str
    title: str
    created_at: str
    updated_at: str
    profile_uri: str
    schema_version: str = "1.0.0"
    description: Optional[str] = None
    session_id: Optional[str] = None
    sequence: int = 0
    last_event_hash: Optional[str] = None
    mode: str = "monitored"
    selected_profile: str = "process"
    requested_profile: str = "process"
    profile_confidence: str = "low"
    current_phase_id: Optional[str] = None
    current_step_id: Optional[str] = None
    crate_dir: str = ".ro-crate-run/ro-crate"
    event_journal: str = ".ro-crate-run/events.ndjson"
    id_map: str = ".ro-crate-run/id-map.json"
    last_checkpoint: Optional[LastCheckpoint] = None
    dirty: bool = True
    declared_inputs: list[JsonDict] = field(default_factory=list)
    declared_outputs: list[JsonDict] = field(default_factory=list)
    known_outputs: list[JsonDict] = field(default_factory=list)
    known_software: list[JsonDict] = field(default_factory=list)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Actor:
    type: str
    id: str
    name: str


@dataclass
class EventSource:
    kind: str
    name: str
    version: str = ""


@dataclass
class RcrEvent:
    event_id: str
    event_type: str
    schema_version: str
    run_id: str
    session_id: Optional[str]
    sequence: int
    timestamp: str
    actor: Actor
    source: EventSource
    visibility: str
    phase_id: Optional[str]
    step_id: Optional[str]
    observed: bool
    declared: bool
    inferred: bool
    redacted: bool
    previous_event_hash: Optional[str]
    event_hash: Optional[str]
    payload: JsonDict


@dataclass(frozen=True)
class RedactionResult:
    text: str
    applied: int = 0
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrivacyFinding:
    severity: str
    code: str
    path: str = ""


@dataclass
class ValidationFinding:
    level: str
    code: str
    message: str
    path: str = ""


@dataclass
class ValidationReport:
    status: str
    profile: str
    profile_uri: str
    levels: dict[str, str]
    errors: list[ValidationFinding] = field(default_factory=list)
    warnings: list[ValidationFinding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class CommandRecord:
    command_id: str
    event_id: str
    action_id: str
    argv: list[str]
    display_command: str
    cwd: str
    started_at: str
    ended_at: Optional[str] = None
    terminal_status: str = "started"
    exit_code: Optional[int] = None
    step_id: Optional[str] = None
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    stdout_log: Optional[str] = None
    stderr_log: Optional[str] = None
    sidecar: Optional[str] = None


@dataclass
class RunModel:
    run_id: str
    title: str
    description: str
    created_at: str
    updated_at: str
    selected_profile: str
    requested_profile: str
    profile_uri: str
    mode: str
    profile_confidence: Optional[str] = None
    profile_evidence: list[str] = field(default_factory=list)
    inputs: list[JsonDict] = field(default_factory=list)
    outputs: list[JsonDict] = field(default_factory=list)
    parameters: list[JsonDict] = field(default_factory=list)
    software: list[JsonDict] = field(default_factory=list)
    notes: list[JsonDict] = field(default_factory=list)
    decisions: list[JsonDict] = field(default_factory=list)
    phases: dict[str, JsonDict] = field(default_factory=dict)
    steps: dict[str, JsonDict] = field(default_factory=dict)
    commands: list[CommandRecord] = field(default_factory=list)
    workflow: Optional[JsonDict] = None
    events: list[RcrEvent] = field(default_factory=list)
    aborted: bool = False
    results: list[JsonDict] = field(default_factory=list)
    # Provenance context projected from environment.observed / container.observed / dependency.lockfile.observed.
    git: JsonDict = field(default_factory=dict)
    environment: JsonDict = field(default_factory=dict)
    containers: list[JsonDict] = field(default_factory=list)
    dependencies: list[JsonDict] = field(default_factory=list)
    # The Claude Code agent's own actions are treated as the workflow.
    # Each list is projected from the corresponding journal events.
    file_actions: list[JsonDict] = field(default_factory=list)      # file.created/modified/changed/deleted
    raw_commands: list[JsonDict] = field(default_factory=list)      # substantive raw Bash (tool.completed)
    subagents: list[JsonDict] = field(default_factory=list)         # agent.task.* / agent.subagent.*
    blocked_actions: list[JsonDict] = field(default_factory=list)   # tool.blocked / permission.denied
    prompts: list[JsonDict] = field(default_factory=list)           # human.prompt
    tool_uses: list[JsonDict] = field(default_factory=list)         # other tool.completed (Read/Grep/MCP/...)
    housekeeping: list[JsonDict] = field(default_factory=list)      # cwd.changed / worktree.* / compaction.*
    # Human decision points captured via PostToolUse on AskUserQuestion / Exit/EnterPlanMode.
    # Each dict: {"sequence": int, "timestamp": str, "tool": str, "question": str|None,
    #             "options": list[str], "answer": str|None, "plan": str|None}.
    tool_decisions: list[JsonDict] = field(default_factory=list)


def strip_none(value: Any) -> Any:
    """Recursively drop dict keys and list elements whose value is None, for crate JSON-LD assembly."""
    if isinstance(value, dict):
        return {k: strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [strip_none(v) for v in value if v is not None]
    return value
