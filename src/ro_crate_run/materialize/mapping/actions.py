"""Command-action and agent-action family builders.

``build_command_action`` materializes one ``rcr run`` command (action + sidecar/log
File entities). ``build_agent_actions`` is the dispatcher that turns the agent's own
work — file edits, raw shell commands, subagent dispatches, blocked tool calls, user
prompts, tool uses, housekeeping, human accept/reject results, and declared phases —
into crate actions; the synthesized agent workflow's steps are derived from these.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ro_crate_run import constants
from ro_crate_run.ids import IdMap, file_ref, relative_file_id, software_entity_id
from ro_crate_run.models import CommandRecord, RunModel

from ._helpers import _content_size, command_action_type


def _agent_action(
    action_id: str,
    type_: str,
    name: str,
    description: str,
    start: Any,
    end: Any,
    *,
    agent: str = "#actor/claude-code",
    status: str = constants.ACTION_STATUS_COMPLETED,
    **extra: Any,
) -> dict[str, Any]:
    """Build the common action-entity skeleton shared across the agent-action builders.

    The fixed envelope is ``{@id,@type,name,description,startTime,endTime,actionStatus,agent}``;
    ``agent`` and ``status`` are overridable (human-attributed and phase/blocked actions vary
    them) and ``**extra`` carries builder-specific keys (instrument/object/result/error).
    """
    action: dict[str, Any] = {
        "@id": action_id,
        "@type": type_,
        "name": name,
        "description": description,
        "startTime": start,
        "endTime": end,
        "actionStatus": {"@id": status},
        "agent": {"@id": agent},
    }
    action.update(extra)
    return action


def build_command_action(
    cmd: CommandRecord,
    idmap: IdMap,
    project_dir: os.PathLike[str] | str,
    env_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return [action_entity, *log_sidecar_file_entities] for one command.

    ``env_ids`` (optional) are the ``#env/*`` PropertyValue ids emitted by
    ``build_environment``; when present they are referenced from the action via
    ``environment`` (Process 0.5 conditional SHOULD).
    """
    action_type = command_action_type(cmd)
    completed = cmd.terminal_status == "completed"
    status = constants.completed_or_failed(completed)
    instrument_name = os.path.basename(cmd.argv[0]) if cmd.argv else "unknown"
    instrument = software_entity_id(instrument_name)
    proj = Path(project_dir)

    action: dict[str, Any] = {
        "@id": cmd.action_id,
        "@type": action_type,
        "name": _action_name(cmd),
        "description": "Executed command; full invocation recorded in command sidecar.",
        "startTime": cmd.started_at,
        "endTime": cmd.ended_at or cmd.started_at,
        "actionStatus": {"@id": status},
        "agent": {"@id": "#actor/human"},
        "instrument": {"@id": instrument},
        "object": [file_ref(Path(p), proj) for p in cmd.inputs],
        "result": [file_ref(Path(p), proj) for p in cmd.outputs],
    }
    if not completed:
        action["error"] = f"Command exited with code {cmd.exit_code}; see stderr log."
    if env_ids:
        # L5: Process 0.5 conditional SHOULD — env vars affecting the run SHOULD be on the
        # action via `environment` → PropertyValue. Refs only; entities come from build_environment.
        action["environment"] = [{"@id": eid} for eid in env_ids]
    entities: list[dict[str, Any]] = [action]
    for rel, label in [
        (cmd.sidecar, "invocation record"),
        (cmd.stdout_log, "stdout"),
        (cmd.stderr_log, "stderr"),
    ]:
        if rel:
            sidecar_entity: dict[str, Any] = {
                "@id": rel,
                "@type": "File",
                "name": f"{cmd.command_id} {label}",
                "encodingFormat": "application/json" if rel.endswith(".json") else "text/plain",
                "about": {"@id": cmd.action_id},
            }
            # Base 1.2 SHOULD — contentSize on the sidecar/log File entity.
            size = _content_size(rel, project_dir)
            if size is not None:
                sidecar_entity["contentSize"] = size
            entities.append(sidecar_entity)
    return entities


def _action_name(cmd: CommandRecord) -> str:
    """Deterministic, unique name derived from the display command and command id."""
    base = cmd.display_command.strip() if cmd.display_command else " ".join(cmd.argv)
    if not base:
        base = cmd.command_id
    # Suffix the command id to guarantee uniqueness when two commands share the same display text.
    return f"{base} [{cmd.command_id}]"


# ---------------------------------------------------------------------------
# Agent action families: the agent's own actions ARE the workflow
# ---------------------------------------------------------------------------


_FILE_OP_TYPE = {
    "created": "CreateAction",
    "modified": "UpdateAction",
    "changed": "UpdateAction",
    "deleted": "DeleteAction",
}


def build_file_actions(
    model: RunModel,
    project_dir: os.PathLike[str] | str,
    emitted_file_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Emit a Create/Update/DeleteAction for every agent file edit (Write/Edit/…),
    plus the tool SoftwareApplication used as the action instrument.

    Drops actions whose target File entity was suppressed by file policy
    (ignored/sensitive/out-of-root) so result/object refs never dangle.
    """
    entities: list[dict[str, Any]] = []
    seen_tools: set[str] = set()
    for fa in model.file_actions:
        path = str(fa.get("path", ""))
        if not path:
            continue
        rel = relative_file_id(Path(path), Path(project_dir))
        # Only materialize the action if its target file became a File entity; otherwise
        # the result/object ref would dangle (fail-safe: drop rather than dangle).
        if emitted_file_ids is not None and rel not in emitted_file_ids:
            continue
        tool = str(fa.get("tool_name") or "editor")
        tool_id = software_entity_id(tool)
        if tool_id not in seen_tools:
            seen_tools.add(tool_id)
            entities.append({"@id": tool_id, "@type": "SoftwareApplication", "name": tool})
        op = str(fa.get("op", "modified"))
        ref = {"@id": rel}
        action = _agent_action(
            f"#file-action/{fa.get('sequence')}",
            _FILE_OP_TYPE.get(op, "UpdateAction"),
            f"{tool} {os.path.basename(rel)}",
            f"Claude agent {op} {rel} via the {tool} tool.",
            fa.get("timestamp"),
            fa.get("timestamp"),
            instrument={"@id": tool_id},
        )
        action["object" if op == "deleted" else "result"] = [ref]
        entities.append(action)
    return entities


def build_raw_command_actions(model: RunModel) -> list[dict[str, Any]]:
    """Emit a CreateAction for each substantive raw shell command (not via rcr run)."""
    entities: list[dict[str, Any]] = []
    seen_tools: set[str] = set()
    for rc in model.raw_commands:
        command = str(rc.get("command", "")).strip()
        if not command:
            continue
        argv0 = os.path.basename(command.split()[0])
        tool_id = software_entity_id(argv0)
        if tool_id not in seen_tools:
            seen_tools.add(tool_id)
            entities.append({"@id": tool_id, "@type": "SoftwareApplication", "name": argv0})
        entities.append(
            _agent_action(
                f"#raw-command/{rc.get('sequence')}",
                "CreateAction",
                command[:100],
                "Raw shell command run by the agent outside rcr run.",
                rc.get("timestamp"),
                rc.get("timestamp"),
                instrument={"@id": tool_id},
                # Process 0.5 — object MAY. rcr cannot infer the outputs of an unwrapped bash
                # command (so result is intentionally absent), but the command operates on the
                # crate's root dataset, so reference it via `object` to improve SHOULD-quality.
                object=[{"@id": "./"}],
            )
        )
    return entities


def build_subagent_actions(model: RunModel) -> list[dict[str, Any]]:
    """Emit an Action for each subagent/Task the agent dispatched."""
    by_task: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for s in model.subagents:
        tid = str(s.get("task_id") or f"seq{s.get('sequence')}")
        event = str(s.get("event", ""))
        if tid not in by_task:
            by_task[tid] = dict(s)
            order.append(tid)
        if event.endswith(("completed", "stopped")):
            by_task[tid]["end"] = s.get("timestamp")
        if event.endswith(("created", "started")) and s.get("description"):
            by_task[tid].setdefault("description", s.get("description"))
    entities: list[dict[str, Any]] = []
    for tid in order:
        s = by_task[tid]
        # OrganizeAction is reserved (Provenance 0.5) for the engine-orchestration hierarchy
        # (instrument=engine, object=ControlActions, result=workflow CreateAction). A subagent
        # dispatch has none of those roles, so it is a generic Action.
        entities.append(
            _agent_action(
                f"#subagent/{s.get('sequence')}",
                "Action",
                f"Dispatch subagent {s.get('subagent_type') or tid}",
                str(s.get("description") or "Subagent task dispatched by the agent."),
                s.get("timestamp"),
                s.get("end", s.get("timestamp")),
            )
        )
    return entities


def build_blocked_actions(model: RunModel) -> list[dict[str, Any]]:
    """Emit a FailedActionStatus Action for each blocked tool call / denied permission."""
    entities: list[dict[str, Any]] = []
    for b in model.blocked_actions:
        reason = str(b.get("reason") or "blocked")
        label = "Failed" if b.get("kind") == "tool-failed" else "Blocked"
        entities.append(
            _agent_action(
                f"#blocked/{b.get('sequence')}",
                "Action",
                f"{label}: {b.get('tool_name') or b.get('kind') or 'action'}",
                reason,
                b.get("timestamp"),
                b.get("timestamp"),
                status=constants.ACTION_STATUS_FAILED,
                error=reason,
            )
        )
    return entities


def build_prompts(model: RunModel) -> list[dict[str, Any]]:
    """Emit a CreativeWork for each user prompt (the run's instruction provenance)."""
    entities: list[dict[str, Any]] = []
    for p in model.prompts:
        entities.append({
            "@id": f"#prompt/{p.get('sequence')}",
            "@type": "CreativeWork",
            "name": f"User prompt {p.get('sequence')}",
            "text": str(p.get("prompt", "")),
            "about": {"@id": "./"},
        })
    return entities


def build_tool_uses(model: RunModel) -> list[dict[str, Any]]:
    """Emit one Action per distinct non-file, non-Bash tool the agent used (with a count)."""
    counts: dict[str, int] = {}
    first_ts: dict[str, Any] = {}
    last_ts: dict[str, Any] = {}
    for t in model.tool_uses:
        name = str(t.get("tool_name", ""))
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        first_ts.setdefault(name, t.get("timestamp"))
        last_ts[name] = t.get("timestamp")
    entities: list[dict[str, Any]] = []
    for name, count in counts.items():
        entities.append(
            _agent_action(
                f"#tool-use/{name}",
                "Action",
                f"Used {name} ({count}x)",
                f"The agent used the {name} tool {count} time(s).",
                first_ts.get(name),
                last_ts.get(name),
            )
        )
    return entities


def build_housekeeping(model: RunModel) -> list[dict[str, Any]]:
    """Emit an Action for each housekeeping event (cwd change, worktree, compaction)."""
    entities: list[dict[str, Any]] = []
    for h in model.housekeeping:
        event = str(h.get("event", ""))
        detail = str(h.get("detail", ""))
        entities.append(
            _agent_action(
                f"#housekeeping/{h.get('sequence')}",
                "Action",
                event.replace(".", " ").strip() or "housekeeping",
                f"{event}{': ' + detail if detail else ''}",
                h.get("timestamp"),
                h.get("timestamp"),
            )
        )
    return entities


def build_results(model: RunModel) -> list[dict[str, Any]]:
    """Emit an AssessAction for each human accept/reject of a result."""
    entities: list[dict[str, Any]] = []
    for idx, r in enumerate(model.results, start=1):
        accepted = bool(r.get("accepted"))
        entity = _agent_action(
            f"#result/{idx}",
            "AssessAction",
            "Accepted result" if accepted else "Rejected result",
            str(r.get("text", "")),
            r.get("timestamp"),
            r.get("timestamp"),
            agent="#actor/human",
            status=constants.completed_or_failed(accepted),
            object={"@id": "./"},
        )
        if not accepted:
            # A FailedActionStatus action must carry an error (L3 profile rule).
            entity["error"] = str(r.get("text", "")) or "result rejected"
        entities.append(entity)
    return entities


def build_phase_actions(model: RunModel) -> list[dict[str, Any]]:
    """Emit an Action grouping for each declared phase of the agent's work."""
    entities: list[dict[str, Any]] = []
    for idx, (name, phase) in enumerate(model.phases.items(), start=1):
        status = phase.get("status", "")
        # OrganizeAction is reserved (Provenance 0.5) for engine orchestration; a human
        # work-phase grouping is a generic Action. The grouping is Active until completed.
        entities.append(
            _agent_action(
                f"#phase/{idx}",
                "Action",
                f"Phase: {name}",
                f"Project phase {name!r} ({status or 'started'}).",
                phase.get("timestamp"),
                phase.get("end_timestamp") or phase.get("timestamp"),
                agent="#actor/human",
                status=constants.completed_or_active(status == "completed"),
            )
        )
    return entities


def build_agent_actions(
    model: RunModel,
    project_dir: os.PathLike[str] | str,
    emitted_file_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate every agent-action family into crate entities."""
    entities: list[dict[str, Any]] = []
    entities += build_file_actions(model, project_dir, emitted_file_ids)
    entities += build_raw_command_actions(model)
    entities += build_subagent_actions(model)
    entities += build_blocked_actions(model)
    entities += build_prompts(model)
    entities += build_tool_uses(model)
    entities += build_housekeeping(model)
    entities += build_results(model)
    entities += build_phase_actions(model)
    return entities
