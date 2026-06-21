"""Project-wide literal constants (RO-Crate/profile URIs, the registered event-type
vocabulary checked by the L0 validator) and small pure helpers derived from them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RO_CRATE_VERSION = "1.2"
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.2/context"
RO_CRATE_SPEC_URI = "https://w3id.org/ro/crate/1.2"
WORKFLOW_RUN_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"

# @id of the RO-Crate root dataset entity (the crate's top-level Dataset node).
ROOT_DATASET_ID: str = "./"

# Byte count in one megabyte; used to convert configured size limits (in MB) to bytes.
BYTES_PER_MB: int = 1024 * 1024

# schema_version stamped on every journal event (the L0 validator checks the field's
# presence, not its value); bumped when the on-disk event shape changes.
EVENT_SCHEMA_VERSION: str = "1.1.0"

# schema_version stamped on a command sidecar record (.ro-crate-run/commands/*.json);
# distinct from ids.ID_MAP_SCHEMA_VERSION (same value today, but a different schema).
SIDECAR_SCHEMA_VERSION: str = "1.0.0"

# Accepted values for the CLI `--existence` argument on `rcr input/output`, in choice order.
# "observed local"/"observed remote" carry a space (not a hyphen) by design.
EXISTENCE_VALUES: tuple[str, ...] = (
    "observed local",
    "observed remote",
    "generated",
    "expected",
    "missing",
    "declared-only",
)

# Existence classes that were actually observed (a probe or filesystem check confirmed
# the declaration), keyed by the "observed " value family. is_observed() replaces the
# scattered `startswith("observed")` checks so the space-bearing literals stay enforced.
EXISTENCE_OBSERVED: tuple[str, ...] = ("observed local", "observed remote")

# Existence classes whose value does NOT imply local on-disk presence: a remote artifact,
# or a declaration of something expected/missing/declared-only. is_absent() drives the
# validator's "legitimately absent on disk" exemption (referenced_file_missing).
EXISTENCE_ABSENT: tuple[str, ...] = (
    "observed remote",
    "expected",
    "missing",
    "declared-only",
)


def is_observed(value: str) -> bool:
    """True when an existence class was actually observed (local or remote)."""
    return value in EXISTENCE_OBSERVED


def is_absent(value: str) -> bool:
    """True when an existence class does not imply a local file present on disk."""
    return value in EXISTENCE_ABSENT


# Exit code recorded for a command that fails to start (e.g. executable not found),
# matching the shell convention of 127 for "command not found".
STARTUP_EXIT_CODE: int = 127

# Environment variable names captured by default when recording a run's environment.
# Kept deliberately small to avoid leaking secrets carried in arbitrary env vars.
DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "LANG",
    "LC_ALL",
    "SHELL",
    "PYTHONPATH",
    "CONDA_DEFAULT_ENV",
    "VIRTUAL_ENV",
)

# Event types that close out a run: once one is appended, the run is no longer active.
RUN_TERMINAL_EVENTS: frozenset[str] = frozenset({"run.finalized", "run.aborted"})

# Event types that finish an execution.command.started record, fixing its exit code
# and terminal status (completed / failed / blocked).
COMMAND_TERMINAL_EVENTS: frozenset[str] = frozenset(
    {
        "execution.command.completed",
        "execution.command.failed",
        "execution.command.blocked",
    }
)

# Event types that mark a workflow step as finished, regardless of outcome. Mirrors the
# set the run-model reducer (materialize/run_model.py) uses for step-terminal detection.
STEP_TERMINAL_EVENTS: frozenset[str] = frozenset(
    {
        "workflow.step.completed",
        "workflow.step.failed",
        "workflow.step.skipped",
    }
)

# Subagent/Task lifecycle events. The run-model reducer folds these into one reduced
# record per task; profiles.py counts the raw events (not the collapsed records) for its
# structured-workflow heuristic. Canonical so the reducer and the heuristic cannot drift.
SUBAGENT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent.task.created",
        "agent.task.completed",
        "agent.subagent.started",
        "agent.subagent.completed",
    }
)

# Permalink to the Workflow RO-Crate 1.0 profile a workflow/provenance crate's root
# also declares (WfRC 0.5 is a superset of Process Run Crate 0.5 + Workflow RO-Crate 1.0).
WORKFLOW_RO_CRATE_URI = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"

_PROCESS_PROFILE_URI = "https://w3id.org/ro/wfrun/process/0.5"


@dataclass(frozen=True)
class ProfileSpec:
    """The fixed facts for one Run-Crate profile, in one place.

    Holds the profile's own conformance URI and display name, the extra profiles a
    workflow-like root also declares, whether the root behaves like a workflow run
    (declares a main workflow + ordered steps), and whether it requires the L3
    HowToStep/ControlAction provenance checks. The materializer, the builder's
    conformsTo logic, and the L3 validator all read these instead of branching on
    the profile name.
    """

    name: str
    uri: str
    # Extra profile URIs a workflow-like root's conformsTo SHOULD also declare
    # (Process Run Crate 0.5 + Workflow RO-Crate 1.0); empty for the flat process profile.
    extra_conformsTo: tuple[str, ...]
    # True when the root behaves like a workflow run, as opposed to the flat process profile.
    is_workflow_like: bool
    # Human-readable name for this profile's contextual Profile entity in the crate.
    label: str
    # True only for the provenance profile: gates the L3 HowToStep/ControlAction checks.
    requires_provenance_steps: bool


# The Run-Crate profile set is spec-fixed (process / workflow / provenance); these specs are
# the one place per-profile facts live. The derived lookups below are computed from PROFILES
# so the registry is the single source.
PROFILES: dict[str, ProfileSpec] = {
    "process": ProfileSpec(
        name="process",
        uri=_PROCESS_PROFILE_URI,
        extra_conformsTo=(),
        is_workflow_like=False,
        label="Process Run Crate",
        requires_provenance_steps=False,
    ),
    "workflow": ProfileSpec(
        name="workflow",
        uri="https://w3id.org/ro/wfrun/workflow/0.5",
        extra_conformsTo=(_PROCESS_PROFILE_URI, WORKFLOW_RO_CRATE_URI),
        is_workflow_like=True,
        label="Workflow Run Crate",
        requires_provenance_steps=False,
    ),
    "provenance": ProfileSpec(
        name="provenance",
        uri="https://w3id.org/ro/wfrun/provenance/0.5",
        extra_conformsTo=(_PROCESS_PROFILE_URI, WORKFLOW_RO_CRATE_URI),
        is_workflow_like=True,
        label="Provenance Run Crate",
        requires_provenance_steps=True,
    ),
}

# Profile name -> conformance URI, derived from the registry. A public lookup many modules
# import directly.
PROFILE_URIS: dict[str, str] = {name: spec.uri for name, spec in PROFILES.items()}

# Display name for each extra-conformsTo profile URI's contextual Profile entity, so the
# builder derives those names from the registry rather than a builder-local dict. Process
# Run Crate reuses the process profile's own label; the Workflow RO-Crate profile is not a
# Run-Crate profile of its own, so its name is given here directly.
EXTRA_CONFORMS_TO_LABELS: dict[str, str] = {
    _PROCESS_PROFILE_URI: PROFILES["process"].label,
    WORKFLOW_RO_CRATE_URI: "Workflow RO-Crate",
}

# Profiles whose root entity behaves like a workflow run (they declare a main
# workflow + ordered steps), as opposed to the flat process profile.
WORKFLOW_LIKE_PROFILES: frozenset[str] = frozenset(
    name for name, spec in PROFILES.items() if spec.is_workflow_like
)

# Accepted values for the CLI/profile selection argument: every known profile plus
# the sentinel "auto" that defers selection to evidence-based detection.
PROFILE_CHOICES: tuple[str, ...] = (*sorted(PROFILES), "auto")


def resolve_profile(requested: str) -> tuple[str, str]:
    """Map a requested profile name to its (selected, uri) pair.

    "auto" resolves to the process profile; an unknown name keeps its given
    selection but falls back to the process profile URI.
    """
    selected = "process" if requested == "auto" else requested
    spec = PROFILES.get(selected, PROFILES["process"])
    return selected, spec.uri


# schema.org actionStatus URIs used on Action entities in the crate.
ACTION_STATUS_COMPLETED = "http://schema.org/CompletedActionStatus"
ACTION_STATUS_FAILED = "http://schema.org/FailedActionStatus"
ACTION_STATUS_ACTIVE = "http://schema.org/ActiveActionStatus"


def completed_or_failed(completed: bool) -> str:
    """Return the Completed or Failed actionStatus URI for a finished action."""
    return ACTION_STATUS_COMPLETED if completed else ACTION_STATUS_FAILED


def completed_or_active(completed: bool) -> str:
    """Return the Completed or Active actionStatus URI for an action that may still run."""
    return ACTION_STATUS_COMPLETED if completed else ACTION_STATUS_ACTIVE


# Lockfiles / package manifests whose presence is treated as a captured dependency
# declaration (excludes container build files, which are tracked separately).
DEPENDENCY_MANIFESTS: tuple[str, ...] = (
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "environment.yml",
    "package-lock.json",
    "pnpm-lock.yaml",
    "renv.lock",
    "Snakefile",
    "nextflow.config",
)

# Container build manifests, tracked separately from dependency manifests.
CONTAINER_MANIFESTS: frozenset[str] = frozenset({"Dockerfile", "Containerfile"})

# @id prefixes that mark an entity identifier as an absolute web/URI reference
# rather than a crate-relative path or blank node.
URI_SCHEME_ID_PREFIXES: tuple[str, ...] = ("http://", "https://", "urn:", "file:")


def is_web_id(eid: str) -> bool:
    """True when an entity @id is an absolute web/URI reference."""
    return eid.startswith(URI_SCHEME_ID_PREFIXES)


def dirty_effect(event_type: str) -> Literal["set", "clear", "preserve"]:
    """Classify how appending an event of this type affects state.dirty.

    Returns "clear" for the checkpoint-completed event that materializes pending
    events into the crate, "preserve" for checkpoint/validation bookkeeping that
    observes but does not materialize, and "set" for any event that introduces
    new provenance the crate has not yet captured.
    """
    if event_type == "crate.checkpoint.completed":
        return "clear"
    if event_type in {"crate.validation.started", "crate.validation.completed"}:
        return "preserve"
    if event_type in {"crate.checkpoint.failed", "crate.validation.failed"}:
        return "set"
    if event_type.startswith("crate.checkpoint"):
        return "preserve"
    return "set"


# Validation level names: the label each layered checker reports its findings under, and
# the keys of the CHECKS pipeline (L0 journal through L5 privacy). Shared by validation/*,
# hooks.py, and commands.py so the level identity has one spelling.
LEVEL_JOURNAL = "journal"
LEVEL_STATE = "state"
LEVEL_ROCRATE = "ro_crate"
LEVEL_PROFILE = "profile"
LEVEL_REPRODUCIBILITY = "reproducibility"
LEVEL_PRIVACY = "privacy"


# date_time tuple stamped on every ZIP entry so a public export is byte-deterministic.
DETERMINISTIC_ZIP_EPOCH: tuple[int, int, int, int, int, int] = (2026, 6, 17, 0, 0, 0)

DEFAULT_STATE_DIR = ".ro-crate-run"
DEFAULT_LICENSE = "https://creativecommons.org/licenses/by/4.0/"

# Central event-type vocabulary. Every type emitted anywhere in the system must be
# listed here; the L0 journal-integrity validator rejects any event whose type is not
# in this set.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Run lifecycle
        "run.started",
        "run.resumed",
        "run.finalized",
        "run.export.blocked",
        "run.aborted",
        "run.config.updated",
        # Environment & system
        "environment.observed",
        "environment.cwd.changed",
        "container.observed",
        "dependency.lockfile.observed",
        # Human actions
        "human.note",
        "human.decision",
        "human.prompt",
        "human.accepted_result",
        "human.rejected_result",
        # Workflow
        "workflow.identified",
        "workflow.input.declared",
        "workflow.output.declared",
        "workflow.parameter.declared",
        "workflow.phase.started",
        "workflow.phase.completed",
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.step.failed",
        "workflow.step.skipped",
        "workflow.step.identified",
        "workflow.profile.selected",
        # Software
        "software.observed",
        # Execution
        "execution.command.started",
        "execution.command.completed",
        "execution.command.failed",
        "execution.command.blocked",
        # Tool events (Claude Code hooks)
        "tool.requested",
        "tool.completed",
        "tool.failed",
        "tool.blocked",
        "tool.batch.completed",
        # Permission
        "permission.requested",
        "permission.denied",
        # Session
        "session.started",
        "session.ended",
        "session.stop.requested",
        "session.stop.failed",
        # Agent
        "agent.task.created",
        "agent.task.completed",
        "agent.subagent.started",
        "agent.subagent.completed",
        # Conversation
        "conversation.compaction.started",
        "conversation.compaction.completed",
        # File events
        "file.observed",
        "file.created",
        "file.modified",
        "file.deleted",
        "file.changed",
        # Git
        "git.worktree.created",
        "git.worktree.removed",
        # Crate / validation / signing
        "crate.checkpoint.started",
        "crate.checkpoint.completed",
        "crate.checkpoint.failed",
        "crate.validation.started",
        "crate.validation.completed",
        "crate.validation.failed",
        "crate.finalized",
        "crate.signed",
        # Redaction
        "redaction.applied",
        "redaction.failed",
        # Journal repair
        "journal.repair.started",
        "journal.repair.completed",
        "journal.repair.failed",
        # Catch-all for unmapped Claude lifecycle hooks (original name in payload.hook_event)
        "hook.unknown",
    }
)
