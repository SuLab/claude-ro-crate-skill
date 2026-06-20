"""Pure reducer: folds the event log up to a high-water sequence into an immutable
RunModel. Crate-output changes belong here, never in stored state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ro_crate_run import adapters
from ro_crate_run.constants import COMMAND_TERMINAL_EVENTS, STEP_TERMINAL_EVENTS
from ro_crate_run.events import event_from_dict
from ro_crate_run.models import CommandRecord, RcrEvent, RunModel
from ro_crate_run.state import load_state, read_events

# A projector folds one event into the model. It mutates `model` in place and may
# read/update the shared `commands_by_id` fold (the only cross-event state). Projectors
# are dispatched in event-iteration order, so the started-before-terminal command fold
# is preserved exactly as in the original sequential elif-ladder.
Projector = Callable[["RunModel", "RcrEvent", "dict[str, CommandRecord]"], None]

# Subagent/Task lifecycle events folded (one reduced record per task) into
# agent_activity.subagents. Shared with profiles.py, which counts the raw lifecycle
# events (not the collapsed records) so its structured-workflow heuristic is unchanged.
SUBAGENT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent.task.created",
        "agent.task.completed",
        "agent.subagent.started",
        "agent.subagent.completed",
    }
)


def build_run_model(state_dir: Path, through_sequence: int | None = None) -> RunModel:
    """Reduce the append-only event journal up to through_sequence into an immutable
    RunModel via pure projection; reads events/state only, never mutates stored state."""
    state = load_state(state_dir)
    raw = [
        item
        for item in read_events(state_dir)
        if through_sequence is None or int(item["sequence"]) <= through_sequence
    ]
    events = [event_from_dict(item) for item in raw]
    model = RunModel(
        run_id=state.run_id,
        title=state.title,
        description=state.description or f"RO-Crate provenance package for {state.title}",
        created_at=state.created_at,
        updated_at=(events[-1].timestamp if events else state.created_at),
        selected_profile=state.selected_profile,
        requested_profile=state.requested_profile,
        profile_uri=state.profile_uri,
        mode=state.mode,
        events=events,
    )
    commands_by_id: dict[str, CommandRecord] = {}
    # One sequential loop preserves event-iteration order; an unregistered event type is a
    # no-op (housekeeping that the crate does not project).
    for event in events:
        projector = _PROJECTORS.get(event.event_type)
        if projector is not None:
            projector(model, event, commands_by_id)
    model.commands = list(commands_by_id.values())
    # Collapse the raw per-event subagent/tool folds into reduced records BEFORE profile
    # selection; profiles.py counts the raw lifecycle events (model.events), not the
    # collapsed records, so its structured-workflow heuristic is unaffected.
    _collapse_agent_activity(model)
    from .profiles import apply_selection, synthesize_workflow
    apply_selection(model, state.requested_profile)
    # The agent's actions are the workflow: when workflow/provenance is selected with no
    # external definition file, synthesize one so the crate conforms (SPEC §16).
    synthesize_workflow(model)
    return model


# --- Workflow declarations -------------------------------------------------------------

def _reduce_input_declared(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.inputs.append(payload)
    path = str(payload.get("path", ""))
    # Recognized workflow-definition shapes come from the adapter registry (the single
    # source of truth for suffix->engine); a declared role overrides path detection.
    if payload.get("role") == "workflow-definition" or adapters.is_workflow_definition(Path(path)):
        model.workflow = {
            "path": payload.get("path"),
            "name": Path(str(payload.get("path"))).name,
            "engine": adapters.engine_for_path(Path(path)) or "unknown",
        }


def _reduce_output_declared(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.outputs.append(event.payload)


def _reduce_parameter_declared(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.parameters.append(event.payload)


def _reduce_workflow_identified(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    # An imported / engine-identified workflow definition (rcr import-ro-crate).
    payload = event.payload
    model.workflow = {
        "path": payload.get("path") or payload.get("workflow_id"),
        "name": payload.get("name") or Path(str(payload.get("path", "workflow"))).name,
        "engine": payload.get("engine", "imported-ro-crate"),
    }


def _reduce_file_observed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    # A file observed in an imported crate — materialize it as a referenced File
    # (reachable from root via mentions) rather than silently dropping it.
    payload = event.payload
    model.inputs.append(
        {
            "path": payload.get("path"),
            "role": payload.get("role", "imported"),
            "description": payload.get("name") or payload.get("path"),
            "existence": "declared-only",
        }
    )


def _reduce_software_observed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.software.append(event.payload)


# --- Human notes / decisions / results -------------------------------------------------

def _reduce_human_note(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.notes.append(event.payload | {"visibility": event.visibility})


def _reduce_human_decision(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.decisions.append(event.payload | {"visibility": event.visibility})


def _reduce_accepted_result(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.results.append(event.payload | {"accepted": True, "timestamp": event.timestamp})


def _reduce_rejected_result(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.results.append(event.payload | {"accepted": False, "timestamp": event.timestamp})


# --- Phases / steps --------------------------------------------------------------------

def _reduce_phase_started(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.phases[str(payload["name"])] = payload | {
        "status": "started", "timestamp": event.timestamp,
    }


def _reduce_phase_completed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    entry = model.phases.setdefault(
        str(payload["name"]), payload | {"timestamp": event.timestamp}
    )
    entry["status"] = "completed"
    entry["end_timestamp"] = event.timestamp


def _reduce_step_started(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    step_id = str(payload["step_id"])
    model.steps[step_id] = payload | {"status": "started"}


def _reduce_step_terminal(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    step_id = str(payload["step_id"])
    model.steps.setdefault(step_id, payload)["status"] = payload.get("status", "completed")


def _reduce_step_identified(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    step_id = str(payload.get("step_id", payload.get("name", "")))
    if step_id and step_id not in model.steps:
        model.steps[step_id] = payload | {"status": "identified"}


# --- Command execution -----------------------------------------------------------------

def _command_argv(payload: dict[str, Any]) -> list[str]:
    """argv for a command record. Real `rcr run` payloads always carry argv; an imported
    Action carries none, so fall back to the display command (then a generic token) — this
    keeps the action's instrument basename resolvable to an emitted #software/* entity
    rather than dangling on #software/unknown, while leaving real commands byte-identical."""
    argv = list(payload.get("argv", []))
    if argv:
        return argv
    return [str(payload.get("display_command", "")) or "imported-action"]


def _reduce_command_started(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    record = CommandRecord(
        command_id=str(payload["command_id"]),
        event_id=event.event_id,
        action_id=str(payload["action_id"]),
        argv=_command_argv(payload),
        display_command=str(payload.get("display_command", "")),
        cwd=str(payload.get("cwd", "")),
        started_at=event.timestamp,
        step_id=event.step_id,
        inputs=list(payload.get("inputs", [])),
        outputs=list(payload.get("outputs", [])),
        stdout_log=payload.get("stdout_log"),
        stderr_log=payload.get("stderr_log"),
        sidecar=payload.get("sidecar"),
    )
    commands_by_id[record.command_id] = record


def _reduce_command_terminal(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    command_id = str(payload["command_id"])
    # setdefault so a terminal-only command (imported Actions emit completed/failed; an
    # importer that does not pair a started would otherwise be dropped) still materializes
    # a CommandRecord. action_id falls back to command_id when no started seeded the record.
    completed_record = commands_by_id.setdefault(
        command_id,
        CommandRecord(
            command_id=command_id,
            event_id=event.event_id,
            action_id=str(payload.get("action_id", command_id)),
            argv=_command_argv(payload),
            display_command=str(payload.get("display_command", "")),
            cwd="",
            started_at=event.timestamp,
            step_id=event.step_id,
        ),
    )
    completed_record.ended_at = str(payload.get("ended_at", event.timestamp))
    completed_record.exit_code = int(payload.get("exit_code", 0))
    if event.event_type == "execution.command.completed":
        completed_record.terminal_status = "completed"
    elif event.event_type == "execution.command.blocked":
        completed_record.terminal_status = "blocked"
    else:
        completed_record.terminal_status = "failed"
    completed_record.inputs = list(payload.get("inputs", completed_record.inputs))
    completed_record.outputs = list(payload.get("outputs", completed_record.outputs))
    completed_record.stdout_log = payload.get("stdout_log", completed_record.stdout_log)
    completed_record.stderr_log = payload.get("stderr_log", completed_record.stderr_log)
    completed_record.sidecar = payload.get("sidecar", completed_record.sidecar)


# --- Environment / containers / dependencies -------------------------------------------

def _reduce_environment_observed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    # Populate git state from the nested git dict if present.
    git_data = payload.get("git")
    if isinstance(git_data, dict) and git_data.get("available"):
        model.git = dict(git_data)
    # Populate environment summary fields.
    env: dict[str, object] = {}
    for key in ("python", "rocrate_package_version", "os", "shell", "claude_model"):
        val = payload.get(key)
        if val is not None:
            env[key] = val
    # Capture allowlisted env vars when present.
    env_vars = payload.get("env_vars")
    if isinstance(env_vars, dict):
        env["env_vars"] = dict(env_vars)
    if env:
        model.environment = env


def _reduce_container_observed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.containers.append(
        {
            "registry": payload.get("registry", ""),
            "image": payload.get("image", ""),
            "tag": payload.get("tag", ""),
            "digest": payload.get("digest", ""),
        }
    )


def _reduce_dependency_observed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.dependencies.append(
        {
            "path": payload.get("path", ""),
            "kind": payload.get("kind", ""),
            "file_record": payload.get("file_record", ""),
        }
    )


def _reduce_run_aborted(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    model.aborted = True


# --- Agent actions: file edits / prompts / blocked / subagents / tool.completed --------

def _reduce_file_action(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    # An agent file edit (Write/Edit/MultiEdit/NotebookEdit, or an external FileChanged).
    # Skip edits to the internal provenance store — they are tooling, not the agent's
    # work product, and must not become workflow steps.
    payload = event.payload
    fa_path = str(payload.get("path", ""))
    if "/.ro-crate-run/" in fa_path or fa_path.startswith(".ro-crate-run/"):
        return
    model.agent_activity.file_actions.append({
        "path": str(payload.get("path", "")),
        "tool_name": str(payload.get("tool_name", "")),
        "op": event.event_type.split(".", 1)[1],
        "timestamp": event.timestamp,
        "sequence": event.sequence,
        "step_id": event.step_id,
        "phase_id": event.phase_id,
    })


def _reduce_prompt(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.agent_activity.prompts.append({
        "prompt": str(payload.get("prompt", "")),
        "prompt_hash": str(payload.get("prompt_hash", "")),
        "timestamp": event.timestamp,
        "sequence": event.sequence,
    })


def _reduce_tool_blocked(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.agent_activity.blocked_actions.append({
        "tool_name": str(payload.get("tool_name", "")),
        "command": str(payload.get("command", "")),
        "reason": str(payload.get("reason", "")),
        "timestamp": event.timestamp,
        "sequence": event.sequence,
        "kind": "policy",
    })


def _reduce_permission_denied(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.agent_activity.blocked_actions.append({
        "tool_name": str(payload.get("tool_name", payload.get("tool", ""))),
        "reason": str(payload.get("reason", payload.get("message", "permission denied"))),
        "timestamp": event.timestamp,
        "sequence": event.sequence,
        "kind": "permission",
    })


def _reduce_tool_failed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.agent_activity.blocked_actions.append({
        "tool_name": str(payload.get("tool_name", "")),
        "reason": str(payload.get("error") or payload.get("message") or "tool use failed"),
        "timestamp": event.timestamp,
        "sequence": event.sequence,
        "kind": "tool-failed",
    })


def _reduce_subagent(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.agent_activity.subagents.append({
        "event": event.event_type,
        "description": str(
            payload.get("description")
            or payload.get("prompt")
            or payload.get("subagent_type")
            or ""
        ),
        "subagent_type": str(payload.get("subagent_type", "")),
        "task_id": str(
            payload.get("task_id") or payload.get("id") or payload.get("agentId") or ""
        ),
        "timestamp": event.timestamp,
        "sequence": event.sequence,
    })


def _reduce_tool_completed(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    tool_name = str(payload.get("tool_name", ""))
    command = _bash_command(payload)
    if tool_name in {"AskUserQuestion", "ExitPlanMode", "EnterPlanMode"}:
        decision = _tool_decision(tool_name, payload, event.timestamp, event.sequence)
        if decision is not None:
            model.agent_activity.tool_decisions.append(decision)
    elif tool_name == "Bash" and command and not _is_rcr_invocation(command):
        # Substantive raw shell NOT wrapped in rcr run (rcr-wrapped commands are
        # already captured as execution.command.* -> CommandRecord; rcr/hook
        # provenance tooling is excluded so it never pollutes the workflow).
        model.agent_activity.raw_commands.append({
            "command": command,
            "timestamp": event.timestamp,
            "sequence": event.sequence,
            "step_id": event.step_id,
        })
    elif tool_name and tool_name != "Bash":
        model.agent_activity.tool_uses.append({
            "tool_name": tool_name,
            "timestamp": event.timestamp,
            "sequence": event.sequence,
        })


def _reduce_housekeeping(
    model: RunModel, event: RcrEvent, commands_by_id: dict[str, CommandRecord]
) -> None:
    payload = event.payload
    model.agent_activity.housekeeping.append({
        "event": event.event_type,
        "detail": str(
            payload.get("new_cwd") or payload.get("path") or payload.get("cwd") or ""
        ),
        "timestamp": event.timestamp,
        "sequence": event.sequence,
    })


def _collapse_agent_activity(model: RunModel) -> None:
    """Reduce the raw per-event subagent/tool records folded during the loop into
    already-reduced records (one per task / one per tool), so the mapping builders stay
    pure 1:1 projectors. This is reduction, so it belongs in the reducer, not the builders.
    """
    activity = model.agent_activity
    activity.subagents = _reduce_subagent_records(activity.subagents)
    activity.tool_uses = _reduce_tool_use_records(activity.tool_uses)


def _reduce_subagent_records(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold raw subagent lifecycle events into one record per task (first-seen order).

    The grouping key is ``task_id`` (falling back to ``seq{sequence}`` when absent) and is
    stored back as ``task_id`` so the builder's name fallback (`subagent_type or task_id`)
    resolves it. ``end`` is taken from the completed/stopped event; ``description`` is
    back-filled from the created/started event; ``sequence``/``timestamp`` stay the first
    event's, preserving the action's @id and startTime.
    """
    by_task: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for s in raw:
        tid = str(s.get("task_id") or f"seq{s.get('sequence')}")
        event_type = str(s.get("event", ""))
        if tid not in by_task:
            record = dict(s)
            record["task_id"] = tid
            by_task[tid] = record
            order.append(tid)
        if event_type.endswith(("completed", "stopped")):
            by_task[tid]["end"] = s.get("timestamp")
        if event_type.endswith(("created", "started")) and s.get("description"):
            by_task[tid].setdefault("description", s.get("description"))
    return [by_task[tid] for tid in order]


def _reduce_tool_use_records(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold raw non-Bash tool uses into one record per tool name (first-seen order),
    carrying the use ``count`` plus first/last timestamps the builder maps 1:1."""
    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for t in raw:
        name = str(t.get("tool_name", ""))
        if not name:
            continue
        if name not in records:
            records[name] = {
                "tool_name": name,
                "count": 0,
                "first_ts": t.get("timestamp"),
                "last_ts": t.get("timestamp"),
            }
            order.append(name)
        records[name]["count"] += 1
        records[name]["last_ts"] = t.get("timestamp")
    return [records[name] for name in order]


# Registry mapping event_type -> projector. Cohesive families (command/step terminals,
# file-action ops, subagent lifecycle, housekeeping) share one projector; adding an
# event type means registering one entry here (plus constants.EVENT_TYPES + dirty_effect).
_PROJECTORS: dict[str, Projector] = {
    "workflow.input.declared": _reduce_input_declared,
    "workflow.output.declared": _reduce_output_declared,
    "workflow.parameter.declared": _reduce_parameter_declared,
    "workflow.identified": _reduce_workflow_identified,
    "file.observed": _reduce_file_observed,
    "software.observed": _reduce_software_observed,
    "human.note": _reduce_human_note,
    "human.decision": _reduce_human_decision,
    "human.accepted_result": _reduce_accepted_result,
    "human.rejected_result": _reduce_rejected_result,
    "workflow.phase.started": _reduce_phase_started,
    "workflow.phase.completed": _reduce_phase_completed,
    "workflow.step.started": _reduce_step_started,
    "workflow.step.identified": _reduce_step_identified,
    "execution.command.started": _reduce_command_started,
    "environment.observed": _reduce_environment_observed,
    "container.observed": _reduce_container_observed,
    "dependency.lockfile.observed": _reduce_dependency_observed,
    "run.aborted": _reduce_run_aborted,
    "human.prompt": _reduce_prompt,
    "tool.blocked": _reduce_tool_blocked,
    "permission.denied": _reduce_permission_denied,
    "tool.failed": _reduce_tool_failed,
    "tool.completed": _reduce_tool_completed,
    "file.created": _reduce_file_action,
    "file.modified": _reduce_file_action,
    "file.changed": _reduce_file_action,
    "file.deleted": _reduce_file_action,
    "environment.cwd.changed": _reduce_housekeeping,
    "git.worktree.created": _reduce_housekeeping,
    "git.worktree.removed": _reduce_housekeeping,
    "conversation.compaction.started": _reduce_housekeeping,
    "conversation.compaction.completed": _reduce_housekeeping,
    "tool.batch.completed": _reduce_housekeeping,
    "permission.requested": _reduce_housekeeping,
}
# Step- and command-terminal families share one projector each; register every member of
# the canonical constant sets so the registry and the vocabulary cannot drift.
for _step_terminal in STEP_TERMINAL_EVENTS:
    _PROJECTORS[_step_terminal] = _reduce_step_terminal
for _command_terminal in COMMAND_TERMINAL_EVENTS:
    _PROJECTORS[_command_terminal] = _reduce_command_terminal
for _subagent_event in SUBAGENT_EVENT_TYPES:
    _PROJECTORS[_subagent_event] = _reduce_subagent


def _bash_command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        return str(tool_input.get("command", ""))
    return ""


def _tool_decision(
    tool_name: str, payload: dict[str, Any], timestamp: str, sequence: int
) -> dict[str, Any] | None:
    """Project a human decision-point tool.completed event into a tool_decisions dict.

    Expected shapes of the PostToolUse tool.completed event:
      - AskUserQuestion: tool_input.questions[] (each {header, question, multiSelect,
        options[]{label, description}}); tool_response.answers[] (each {header, question,
        selected[]}). A single call may carry multiple questions.
      - Exit/EnterPlanMode: tool_input.plan is the plan text.
    Robust to missing keys (everything via .get); returns None if there is no usable content.
    """
    base: dict[str, Any] = {
        "sequence": sequence,
        "timestamp": timestamp,
        "tool": tool_name,
        "question": None,
        "options": [],
        "answer": None,
        "plan": None,
    }
    if tool_name == "AskUserQuestion":
        question, options, answer = _extract_ask(payload)
        if question is None and not options and answer is None:
            return None
        base["question"] = question
        base["options"] = options
        base["answer"] = answer
        return base
    # ExitPlanMode / EnterPlanMode
    tool_input = payload.get("tool_input")
    plan = None
    if isinstance(tool_input, dict):
        raw_plan = tool_input.get("plan")
        if raw_plan is not None:
            plan = str(raw_plan)
    if not plan:
        return None
    base["plan"] = plan
    return base


def _extract_ask(
    payload: dict[str, Any],
) -> tuple[str | None, list[str], str | None]:
    """Flatten AskUserQuestion question(s), option labels, and selected answer(s)."""
    tool_input = payload.get("tool_input")
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    question_texts: list[str] = []
    options: list[str] = []
    if isinstance(questions, list):
        for q in questions:
            if not isinstance(q, dict):
                continue
            qtext = q.get("question") or q.get("header")
            if qtext:
                question_texts.append(str(qtext))
            opts = q.get("options")
            if isinstance(opts, list):
                for opt in opts:
                    if isinstance(opt, dict):
                        label = opt.get("label")
                        if label is not None:
                            options.append(str(label))
                    elif opt is not None:
                        options.append(str(opt))
    answers: list[str] = []
    tool_response = payload.get("tool_response")
    raw_answers = tool_response.get("answers") if isinstance(tool_response, dict) else None
    if isinstance(raw_answers, list):
        for ans in raw_answers:
            if isinstance(ans, dict):
                selected = ans.get("selected")
                if isinstance(selected, list):
                    answers.extend(str(s) for s in selected if s is not None)
                elif selected is not None:
                    answers.append(str(selected))
            elif ans is not None:
                answers.append(str(ans))
    question = "; ".join(question_texts) if question_texts else None
    answer = "; ".join(answers) if answers else None
    return question, options, answer


def _is_rcr_invocation(command: str) -> bool:
    """True if a Bash command is rcr / a rocrate hook script — provenance tooling, not
    the agent's work. Matches whether invoked as `rcr ...` or via a full skill path
    (e.g. /…/scripts/rcr start) so it never becomes a raw-command workflow step."""
    stripped = command.strip()
    if not stripped:
        return False
    if "rocrate_" in stripped:
        return True
    first = stripped.split()[0]
    return Path(first).name == "rcr"
