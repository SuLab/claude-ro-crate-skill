from __future__ import annotations

from pathlib import Path
from typing import Any

from ro_crate_run.events import event_from_dict
from ro_crate_run.models import CommandRecord, RunModel
from ro_crate_run.state import load_state, read_events


def build_run_model(state_dir: Path, through_sequence: int | None = None) -> RunModel:
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
    for event in events:
        payload = event.payload
        if event.event_type == "workflow.input.declared":
            model.inputs.append(payload)
            if (
                payload.get("role") == "workflow-definition"
                or str(payload.get("path", "")).endswith((".cwl", ".nf", ".wdl", ".ga"))
                or Path(str(payload.get("path", ""))).name in {"Snakefile"}
            ):
                model.workflow = {
                    "path": payload.get("path"),
                    "name": Path(str(payload.get("path"))).name,
                    "engine": _engine_for_path(str(payload.get("path"))),
                }
        elif event.event_type == "workflow.output.declared":
            model.outputs.append(payload)
        elif event.event_type == "workflow.parameter.declared":
            model.parameters.append(payload)
        elif event.event_type == "software.observed":
            model.software.append(payload)
        elif event.event_type == "human.note":
            model.notes.append(payload | {"visibility": event.visibility})
        elif event.event_type == "human.decision":
            model.decisions.append(payload | {"visibility": event.visibility})
        elif event.event_type == "workflow.phase.started":
            model.phases[str(payload["name"])] = payload | {
                "status": "started", "timestamp": event.timestamp,
            }
        elif event.event_type == "workflow.phase.completed":
            entry = model.phases.setdefault(
                str(payload["name"]), payload | {"timestamp": event.timestamp}
            )
            entry["status"] = "completed"
            entry["end_timestamp"] = event.timestamp
        elif event.event_type == "workflow.step.started":
            step_id = str(payload["step_id"])
            model.steps[step_id] = payload | {"status": "started"}
        elif event.event_type in {
            "workflow.step.completed",
            "workflow.step.failed",
            "workflow.step.skipped",
        }:
            step_id = str(payload["step_id"])
            model.steps.setdefault(step_id, payload)["status"] = payload.get("status", "completed")
        elif event.event_type == "execution.command.started":
            record = CommandRecord(
                command_id=str(payload["command_id"]),
                event_id=event.event_id,
                action_id=str(payload["action_id"]),
                argv=list(payload.get("argv", [])),
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
        elif event.event_type in {
            "execution.command.completed",
            "execution.command.failed",
            "execution.command.blocked",
        }:
            completed_record = commands_by_id.get(str(payload["command_id"]))
            if completed_record:
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
        elif event.event_type == "environment.observed":
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
        elif event.event_type == "container.observed":
            model.containers.append(
                {
                    "registry": payload.get("registry", ""),
                    "image": payload.get("image", ""),
                    "tag": payload.get("tag", ""),
                    "digest": payload.get("digest", ""),
                }
            )
        elif event.event_type == "dependency.lockfile.observed":
            model.dependencies.append(
                {
                    "path": payload.get("path", ""),
                    "kind": payload.get("kind", ""),
                    "file_record": payload.get("file_record", ""),
                }
            )
        elif event.event_type == "run.aborted":
            model.aborted = True
        elif event.event_type == "human.accepted_result":
            model.results.append(payload | {"accepted": True, "timestamp": event.timestamp})
        elif event.event_type == "human.rejected_result":
            model.results.append(payload | {"accepted": False, "timestamp": event.timestamp})
        elif event.event_type == "workflow.step.identified":
            step_id = str(payload.get("step_id", payload.get("name", "")))
            if step_id and step_id not in model.steps:
                model.steps[step_id] = payload | {"status": "identified"}
        elif event.event_type in {
            "file.created", "file.modified", "file.changed", "file.deleted",
        }:
            # An agent file edit (Write/Edit/MultiEdit/NotebookEdit, or an external FileChanged).
            # Skip edits to the internal provenance store — they are tooling, not the agent's
            # work product, and must not become workflow steps.
            _fa_path = str(payload.get("path", ""))
            if "/.ro-crate-run/" in _fa_path or _fa_path.startswith(".ro-crate-run/"):
                continue
            model.file_actions.append({
                "path": str(payload.get("path", "")),
                "tool_name": str(payload.get("tool_name", "")),
                "op": event.event_type.split(".", 1)[1],
                "timestamp": event.timestamp,
                "sequence": event.sequence,
                "step_id": event.step_id,
                "phase_id": event.phase_id,
            })
        elif event.event_type == "human.prompt":
            model.prompts.append({
                "prompt": str(payload.get("prompt", "")),
                "prompt_hash": str(payload.get("prompt_hash", "")),
                "timestamp": event.timestamp,
                "sequence": event.sequence,
            })
        elif event.event_type == "tool.blocked":
            model.blocked_actions.append({
                "tool_name": str(payload.get("tool_name", "")),
                "command": str(payload.get("command", "")),
                "reason": str(payload.get("reason", "")),
                "timestamp": event.timestamp,
                "sequence": event.sequence,
                "kind": "policy",
            })
        elif event.event_type == "permission.denied":
            model.blocked_actions.append({
                "tool_name": str(payload.get("tool_name", payload.get("tool", ""))),
                "reason": str(payload.get("reason", payload.get("message", "permission denied"))),
                "timestamp": event.timestamp,
                "sequence": event.sequence,
                "kind": "permission",
            })
        elif event.event_type == "tool.failed":
            model.blocked_actions.append({
                "tool_name": str(payload.get("tool_name", "")),
                "reason": str(
                    payload.get("error") or payload.get("message") or "tool use failed"
                ),
                "timestamp": event.timestamp,
                "sequence": event.sequence,
                "kind": "tool-failed",
            })
        elif event.event_type in {
            "agent.task.created", "agent.task.completed",
            "agent.subagent.started", "agent.subagent.completed",
        }:
            model.subagents.append({
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
        elif event.event_type == "tool.completed":
            tool_name = str(payload.get("tool_name", ""))
            command = _bash_command(payload)
            if tool_name == "Bash" and command and not _is_rcr_invocation(command):
                # Substantive raw shell NOT wrapped in rcr run (rcr-wrapped commands are
                # already captured as execution.command.* -> CommandRecord; rcr/hook
                # provenance tooling is excluded so it never pollutes the workflow).
                model.raw_commands.append({
                    "command": command,
                    "timestamp": event.timestamp,
                    "sequence": event.sequence,
                    "step_id": event.step_id,
                })
            elif tool_name and tool_name != "Bash":
                model.tool_uses.append({
                    "tool_name": tool_name,
                    "timestamp": event.timestamp,
                    "sequence": event.sequence,
                })
        elif event.event_type in {
            "environment.cwd.changed", "git.worktree.created", "git.worktree.removed",
            "conversation.compaction.started", "conversation.compaction.completed",
            "tool.batch.completed", "permission.requested",
        }:
            model.housekeeping.append({
                "event": event.event_type,
                "detail": str(
                    payload.get("new_cwd") or payload.get("path") or payload.get("cwd") or ""
                ),
                "timestamp": event.timestamp,
                "sequence": event.sequence,
            })
    model.commands = list(commands_by_id.values())
    from .profiles import select_profile, synthesize_workflow
    selection = select_profile(model, state.requested_profile)
    model.selected_profile = selection.profile
    model.profile_uri = selection.profile_uri
    # The agent's actions are the workflow: when workflow/provenance is selected with no
    # external definition file, synthesize one so the crate conforms (SPEC §16).
    synthesize_workflow(model)
    return model


def _bash_command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        return str(tool_input.get("command", ""))
    return ""


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


def _engine_for_path(path: str) -> str:
    name = Path(path).name
    if name == "Snakefile" or path.endswith(".smk"):
        return "snakemake"
    if path.endswith(".cwl"):
        return "cwl"
    if path.endswith(".nf") or name == "nextflow.config":
        return "nextflow"
    if path.endswith(".wdl"):
        return "wdl"
    if path.endswith(".ga"):
        return "galaxy"
    return "unknown"
