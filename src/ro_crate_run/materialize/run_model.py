from __future__ import annotations

from pathlib import Path

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
            model.phases[str(payload["name"])] = payload | {"status": "started"}
        elif event.event_type == "workflow.phase.completed":
            model.phases.setdefault(str(payload["name"]), payload)["status"] = "completed"
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
                }
            )
        elif event.event_type == "run.aborted":
            model.aborted = True
        elif event.event_type == "human.accepted_result":
            model.results.append(payload | {"accepted": True})
        elif event.event_type == "human.rejected_result":
            model.results.append(payload | {"accepted": False})
        elif event.event_type == "workflow.step.identified":
            step_id = str(payload.get("step_id", payload.get("name", "")))
            if step_id and step_id not in model.steps:
                model.steps[step_id] = payload | {"status": "identified"}
    model.commands = list(commands_by_id.values())
    from .profiles import select_profile
    selection = select_profile(model, state.requested_profile)
    model.selected_profile = selection.profile
    model.profile_uri = selection.profile_uri
    return model


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
