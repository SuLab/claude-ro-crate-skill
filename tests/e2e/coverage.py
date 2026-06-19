from __future__ import annotations

_COMMANDS = [
    "start", "resume", "status", "note", "decision", "phase", "step",
    "input", "output", "parameter", "software", "run", "checkpoint",
    "validate", "finalize", "inspect", "redact", "export", "hash",
    "import-ro-crate", "sign", "config", "abort", "accept", "reject",
]
_FLAGS = [
    "flag:start:--mode", "flag:start:--profile", "flag:start:--no-checkpoint",
    "flag:note:--public", "flag:note:--private",
    "flag:decision:--rationale", "flag:decision:--public", "flag:decision:--private",
    "flag:input:--role", "flag:input:--description", "flag:input:--required",
    "flag:input:--public", "flag:input:--private", "flag:input:--existence",
    "flag:input:--copy", "flag:input:--reference",
    "flag:output:--role", "flag:output:--description", "flag:output:--required",
    "flag:output:--public", "flag:output:--private", "flag:output:--existence",
    "flag:output:--copy", "flag:output:--reference",
    "flag:parameter:--formal-parameter", "flag:parameter:--type",
    "flag:software:--version", "flag:software:--type",
    "flag:run:--step", "flag:run:--inputs", "flag:run:--outputs",
    "flag:checkpoint:--profile",
    "flag:validate:--strict", "flag:validate:--json",
    "flag:finalize:--zip", "flag:finalize:--include-event-journal",
    "flag:finalize:--sign", "flag:finalize:--public", "flag:finalize:--private",
    "flag:step:start", "flag:step:end",
]
_EXISTENCE = [f"existence:{v}" for v in (
    "observed local", "observed remote", "generated", "expected", "missing", "declared-only",
)]
_ENTITIES = [f"entity:{t}" for t in (
    "Person", "SoftwareApplication", "Dataset", "File", "CreateAction", "UpdateAction",
    "DeleteAction", "Action", "ControlAction", "FormalParameter", "PropertyValue",
    "HowToStep", "ComputationalWorkflow", "ContainerImage", "CreativeWork",
    "Profile", "ParameterConnection", "Thing", "OrganizeAction", "AssessAction",
)]
_PROPS = [f"prop:{p}" for p in (
    "action:object", "action:result", "action:instrument", "action:agent",
    "action:actionStatus", "action:error", "file:sha256", "file:exampleOfWork",
    "git:branch", "git:dirty", "git:remote", "decision:rationale",
    "step:workExample", "workflow:programmingLanguage", "workflow:mainEntity",
)]
_POLICY = [f"policy:{k}" for k in (
    "copy", "reference", "out-of-root-reference", "include_event_journal",
    "include_git_diff", "lockfile-scan",
)]
_PROFILES = ["profile:process", "profile:workflow", "profile:provenance"]
_MODES = ["mode:advisory", "mode:monitored", "mode:enforced"]
_FEATURES = [f"feature:{f}" for f in (
    "auto-profile", "natural-language", "public-export", "export-blocked", "signing",
    "redact-apply", "import", "abort", "recovery-abandoned", "stale-checkpoint",
    "open-phase-warning", "env-allowlist", "custom-redaction", "never-capture",
    "enforced-block-raw-bash", "enforced-block-output-write",
    "enforced-block-destroy", "enforced-block-exfil", "stop-hook-block",
    "agent-file-edits", "auto-start", "raw-bash-action", "subagent-action",
    "tool-use-action", "housekeeping-action", "agent-file-update",
)]

REQUIRED_TAGS = frozenset(
    [f"cmd:{c}" for c in _COMMANDS]
    + _FLAGS + _EXISTENCE + _ENTITIES + _PROPS + _POLICY + _PROFILES + _MODES + _FEATURES
)


def covered_tags(specs: list) -> set:
    out: set = set()
    for s in specs:
        out |= set(s.coverage_tags)
    return out


def missing_tags(specs: list) -> set:
    return set(REQUIRED_TAGS) - covered_tags(specs)


def assert_full_coverage(specs: list) -> None:
    missing = missing_tags(specs)
    assert missing == set(), f"uncovered surface tags: {sorted(missing)}"
