RO_CRATE_VERSION = "1.2"
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.2/context"
RO_CRATE_SPEC_URI = "https://w3id.org/ro/crate/1.2"
WORKFLOW_RUN_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"

PROFILE_URIS = {
    "process": "https://w3id.org/ro/wfrun/process/0.5",
    "workflow": "https://w3id.org/ro/wfrun/workflow/0.5",
    "provenance": "https://w3id.org/ro/wfrun/provenance/0.5",
}

DEFAULT_STATE_DIR = ".ro-crate-run"
DEFAULT_LICENSE = "https://creativecommons.org/licenses/by/4.0/"

# Central event-type vocabulary.  Includes all types emitted by any phase so
# that Phase-5 Level-0 validation can accept them without an allowlist gap.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Run lifecycle
        "run.started",
        "run.resumed",
        "run.finalized",
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
        "human.declared_input",
        "human.declared_output",
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
        "file.hashed",
        "dataset.observed",
        "dataset.hashed",
        # Git
        "git.state.observed",
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
    }
)
