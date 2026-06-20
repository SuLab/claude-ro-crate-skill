"""Workflow, workflow-level action, and step builders.

``build_workflow`` emits the ComputationalWorkflow entity (with hasPart → orchestrated
tools); ``build_workflow_action`` emits the top-level workflow-run action; ``build_steps``
and ``build_workflow_timeline`` emit HowToStep / ControlAction entities (the latter
synthesizes steps from an agent's ordered actions when there are no explicit rcr steps).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ro_crate_run import constants
from ro_crate_run.events import crate_actor_id, engine_actor_id
from ro_crate_run.ids import IdMap, file_ref, software_entity_id
from ro_crate_run.models import CommandRecord, RunModel

from ._helpers import STEP_STATUS_URI, ref
from .parameters import workflow_formal_parameters


def build_workflow(model: RunModel, idmap: IdMap) -> list[dict[str, Any]]:
    """Return the ComputationalWorkflow entity (+ HowTo when steps exist), or []."""
    if not model.workflow:
        return []
    wf_path = str(model.workflow["path"])
    synthetic = bool(model.workflow.get("synthetic"))
    _, formal_param_map = workflow_formal_parameters(model)
    # A synthesized workflow (the agent's own actions) is not a file on disk, so it must
    # NOT carry the "File" type — that would make L2 demand a non-existent file. Its
    # fragment @id (#workflow/...) is also skipped by the file-existence check.
    types: list[str] = (
        ["SoftwareSourceCode", "ComputationalWorkflow"]
        if synthetic
        else ["File", "SoftwareSourceCode", "ComputationalWorkflow"]
    )
    if model.steps:
        types.append("HowTo")
    entity: dict[str, Any] = {
        "@id": wf_path,
        "@type": types,
        "name": model.workflow.get("name", os.path.basename(wf_path)),
        "description": (
            "Workflow describing the actions taken by the Claude Code agent."
            if synthetic
            else "Workflow definition"
        ),
        # Reference the engine SoftwareApplication (#actor/engine/<engine>) build_actors emits,
        # so it is not an orphan; fall back to a plain string for an unknown engine.
        "programmingLanguage": (
            ref(engine_actor_id(str(model.workflow["engine"])))
            if model.workflow.get("engine") and model.workflow["engine"] != "unknown"
            else model.workflow.get("engine", "workflow")
        ),
    }
    input_refs = [
        ref(formal_param_map[str(item.get("path", ""))])
        for item in model.inputs
        if str(item.get("path", "")) in formal_param_map
    ]
    output_refs = [
        ref(formal_param_map[str(item.get("path", ""))])
        for item in model.outputs
        if str(item.get("path", "")) in formal_param_map
    ]
    if input_refs:
        entity["input"] = input_refs
    if output_refs:
        entity["output"] = output_refs
    if model.steps:
        entity["step"] = [
            ref(idmap.entity_for_step(step_id)) for step_id in sorted(model.steps)
        ]
    # Provenance 0.5 MUST — the ComputationalWorkflow's hasPart references the @ids of the
    # orchestrated tools (the SoftwareApplications the steps invoke + the engine). Every ref
    # MUST resolve, so we only list ids that build_software / build_actors actually emit.
    tool_ids = _orchestrated_tool_ids(model)
    if tool_ids:
        entity["hasPart"] = [ref(tid) for tid in tool_ids]
    return [entity]


def _orchestrated_tool_ids(model: RunModel) -> list[str]:
    """Return the ordered, de-duplicated @ids of tools orchestrated by the workflow.

    Sources, all of which are guaranteed emitted elsewhere so the refs resolve:
    - the per-command tool `#software/<basename>` ids (emitted by build_software via commands),
    - the declared-software `#software/<slug>` ids (emitted by build_software),
    - the workflow engine `#actor/engine/<engine>` (emitted by build_actors when known).
    """
    ids: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            ids.append(value)

    for cmd in model.commands:
        if cmd.argv:
            _add(software_entity_id(os.path.basename(cmd.argv[0])))
    for sw in model.software:
        name = str(sw.get("name") or sw.get("command") or "software")
        _add(software_entity_id(name))
    engine = (model.workflow or {}).get("engine")
    if engine and engine != "unknown":
        _add(engine_actor_id(str(engine)))
    return ids


def build_workflow_action(
    model: RunModel,
    idmap: IdMap,
    wf_id: str,
    project_dir: os.PathLike[str] | str,
) -> list[dict[str, Any]]:
    """Return a top-level workflow-run action for workflow/provenance profiles.

    Fires whenever there is execution-shaped work — `rcr run` commands OR the agent's
    own file edits / raw commands — so an edit-only session (no `rcr run`) still has an
    action that uses the workflow as `instrument` (required by L3 workflow).
    """
    if not model.workflow:
        return []
    activity = model.agent_activity
    if not (model.commands or activity.file_actions or activity.raw_commands):
        return []
    proj = Path(project_dir)
    failed = any(c.terminal_status == "failed" for c in model.commands)
    workflow_status = constants.completed_or_failed(not failed)
    workflow_action_id = idmap.entity_for_event(
        f"workflow-run:{model.run_id}", "workflow-action"
    )

    if model.commands:
        start_time = model.commands[0].started_at
        end_time = model.commands[-1].ended_at or model.commands[-1].started_at
        # `rcr run` work is recorded by the rcr materializer.
        agent_id = crate_actor_id("rcr")
    else:
        # Edit-only session: the Claude agent performed the work directly.
        stamps = [
            str(item.get("timestamp", ""))
            for item in (*activity.file_actions, *activity.raw_commands)
            if item.get("timestamp")
        ]
        start_time = min(stamps) if stamps else model.created_at
        end_time = max(stamps) if stamps else model.updated_at
        agent_id = crate_actor_id("claude-code")

    wf_path = str(model.workflow.get("path", ""))
    action: dict[str, Any] = {
        "@id": workflow_action_id,
        "@type": "CreateAction",
        "name": f"Execute workflow for {model.title}",
        "description": "Workflow-level execution action.",
        "startTime": start_time,
        "endTime": end_time,
        "actionStatus": ref(workflow_status),
        "agent": ref(agent_id),
        "instrument": ref(wf_id),
        "object": [
            file_ref(Path(str(item["path"])), proj)
            for item in model.inputs
            if str(item.get("path", "")) != wf_path
        ],
        "result": [file_ref(Path(str(item["path"])), proj) for item in model.outputs],
    }
    if failed:
        # L3: a FailedActionStatus action must carry an error.
        action["error"] = "One or more commands in the workflow failed; see the command actions."
    return [action]


def build_workflow_timeline(
    ordered_actions: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """For a synthesized agent workflow with no explicit rcr steps, turn the agent's
    ordered action sequence INTO the workflow's steps: one HowToStep per action (with a
    1..N position) plus a ControlAction (instrument=HowToStep, object=the action). Returns
    (step+control entities, step refs for the workflow's `step` array). Callers pass only
    actions already emitted in the graph, so refs never dangle.
    """
    entities: list[dict[str, Any]] = []
    step_refs: list[dict[str, str]] = []
    for position, (action_id, name) in enumerate(ordered_actions, start=1):
        step_id = f"#wfstep/{position}"
        entities.append({
            "@id": step_id,
            "@type": "HowToStep",
            "name": name,
            "position": position,
        })
        entities.append({
            "@id": f"#wfcontrol/{position}",
            "@type": "ControlAction",
            "name": f"Step {position}",
            "instrument": ref(step_id),
            "object": ref(action_id),
        })
        step_refs.append(ref(step_id))
    return entities, step_refs


def _step_fallback_workexample(model: RunModel) -> str | None:
    """Return the @id used as a command-less step's `workExample`.

    Prefer the workflow engine SoftwareApplication (`#actor/engine/<engine>`, emitted by
    build_actors when the engine is known); otherwise fall back to the workflow entity
    itself (`model.workflow["path"]`, always present when steps exist). Both refs resolve.
    """
    wf = model.workflow or {}
    engine = wf.get("engine")
    if engine and engine != "unknown":
        return engine_actor_id(str(engine))
    path = wf.get("path")
    return str(path) if path else None


def build_steps(model: RunModel, idmap: IdMap) -> list[dict[str, Any]]:
    """Emit a HowToStep for every step id, plus a ControlAction for steps with
    a mapped command.  Guarantees no dangling step refs from build_workflow.

    The step's lifecycle status (started/completed/failed/skipped) is projected so a
    start→end transition is visible in the crate: as an `additionalProperty` on the
    HowToStep (universal, even for steps with no command) and as the `actionStatus` of the
    controlling ControlAction (which IS an Action).
    """
    if not model.steps:
        return []
    cmd_by_step: dict[str, CommandRecord] = {}
    for cmd in model.commands:
        if cmd.step_id:
            cmd_by_step.setdefault(cmd.step_id, cmd)
    # workExample MUST be set on EVERY HowToStep (Provenance 0.5 MUST). A command-less
    # step (e.g. Snakemake `all`) falls back to the engine SoftwareApplication / the workflow.
    fallback_workexample = _step_fallback_workexample(model)
    entities: list[dict[str, Any]] = []
    for step_id in sorted(model.steps):
        step_entity_id = idmap.entity_for_step(step_id)
        status = str(model.steps[step_id].get("status", "started"))
        howto: dict[str, Any] = {
            "@id": step_entity_id,
            "@type": "HowToStep",
            "name": step_id,
            "additionalProperty": {
                "@type": "PropertyValue",
                "propertyID": "status",
                "value": status,
            },
        }
        step_cmd: CommandRecord | None = cmd_by_step.get(step_id)
        if step_cmd and step_cmd.argv:
            howto["workExample"] = ref(software_entity_id(os.path.basename(step_cmd.argv[0])))
        elif fallback_workexample is not None:
            howto["workExample"] = ref(fallback_workexample)
        entities.append(howto)
        if step_cmd:
            entities.append(
                {
                    "@id": idmap.entity_for_event(f"control:{step_cmd.command_id}", "control"),
                    "@type": "ControlAction",
                    "instrument": ref(step_entity_id),
                    "object": ref(step_cmd.action_id),
                    "actionStatus": ref(
                        STEP_STATUS_URI.get(status, constants.ACTION_STATUS_COMPLETED)
                    ),
                }
            )
    return entities
