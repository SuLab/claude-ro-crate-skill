"""Pure entity builders for RO-Crate graph assembly.

Each function accepts a ``RunModel`` (or closely related inputs) and returns
``list[dict]`` graph fragments.  ``builder.py`` concatenates them, dedupes,
strips nulls, and writes via ro-crate-py.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ro_crate_run import __version__
from ro_crate_run.ids import IdMap, software_entity_id
from ro_crate_run.models import CommandRecord, RunModel

# ---------------------------------------------------------------------------
# Actors (C4)
# ---------------------------------------------------------------------------


def build_actors(model: RunModel) -> list[dict[str, Any]]:
    """Emit stable actor entities for everyone involved in this run."""
    env = model.environment or {}
    actors: list[dict[str, Any]] = [
        {"@id": "#actor/human", "@type": "Person", "name": "Human operator"},
        {
            "@id": "#actor/rcr",
            "@type": "SoftwareApplication",
            "name": "RO-Crate Run",
            "softwareVersion": __version__,
        },
        {"@id": "#actor/claude-code", "@type": "SoftwareApplication", "name": "Claude Code"},
        {
            "@id": "#actor/ro-crate-py",
            "@type": "SoftwareApplication",
            "name": "ro-crate-py",
            "softwareVersion": env.get("rocrate_package_version"),
        },
        {
            "@id": "#actor/python",
            "@type": "SoftwareApplication",
            "name": "Python",
            "softwareVersion": env.get("python"),
        },
    ]
    if env.get("claude_model"):
        actors.append(
            {
                "@id": "#actor/claude-model",
                # SPEC §15.5: model maps to SoftwareApplication (AIModel is not a context term).
                "@type": "SoftwareApplication",
                "name": str(env["claude_model"]),
            }
        )
    if env.get("shell"):
        actors.append(
            {"@id": "#actor/shell", "@type": "SoftwareApplication", "name": str(env["shell"])}
        )
    if model.workflow and model.workflow.get("engine") and model.workflow["engine"] != "unknown":
        engine = str(model.workflow["engine"])
        actors.append(
            {
                "@id": f"#actor/engine/{engine}",
                "@type": "SoftwareApplication",
                "name": engine,
            }
        )
    # Strip None-valued fields before returning.
    return [{k: v for k, v in actor.items() if v is not None} for actor in actors]


# ---------------------------------------------------------------------------
# Software (C9)
# ---------------------------------------------------------------------------

_DELETE_TOOLS = {"rm", "rmdir", "del", "unlink"}


def command_action_type(cmd: CommandRecord) -> str:
    """Return the appropriate schema.org action type for a command."""
    tool = os.path.basename(cmd.argv[0]) if cmd.argv else ""
    if tool in _DELETE_TOOLS:
        return "DeleteAction"
    if cmd.outputs:
        if cmd.inputs and set(cmd.outputs) <= set(cmd.inputs):
            return "UpdateAction"
        return "CreateAction"
    return "Action"


def build_software(model: RunModel) -> list[dict[str, Any]]:
    """Emit a SoftwareApplication entity for every declared software entry and
    every command instrument basename, deduped by @id."""
    entities: dict[str, dict[str, Any]] = {}
    for sw in model.software:
        name = str(sw.get("name") or sw.get("command") or "software")
        sid = software_entity_id(name)
        entities[sid] = {
            "@id": sid,
            "@type": "SoftwareApplication",
            "name": name,
            "softwareVersion": sw.get("version", "unknown"),
        }
    for cmd in model.commands:
        if not cmd.argv:
            continue
        tool = os.path.basename(cmd.argv[0])
        sid = software_entity_id(tool)
        entities.setdefault(sid, {"@id": sid, "@type": "SoftwareApplication", "name": tool})
    return list(entities.values())


# ---------------------------------------------------------------------------
# Command actions (C8)
# ---------------------------------------------------------------------------


def build_command_action(
    cmd: CommandRecord, idmap: IdMap, project_dir: os.PathLike[str] | str
) -> list[dict[str, Any]]:
    """Return [action_entity, *log_sidecar_file_entities] for one command."""
    action_type = command_action_type(cmd)
    completed = cmd.terminal_status == "completed"
    status = (
        "http://schema.org/CompletedActionStatus"
        if completed
        else "http://schema.org/FailedActionStatus"
    )
    instrument_name = os.path.basename(cmd.argv[0]) if cmd.argv else "unknown"
    instrument = software_entity_id(instrument_name)
    proj = Path(project_dir)

    def _file_ref(path: str) -> dict[str, str]:
        p = Path(path)
        if p.is_absolute():
            try:
                rel = str(p.resolve().relative_to(proj.resolve()))
                return {"@id": rel}
            except ValueError:
                return {"@id": p.as_uri()}
        return {"@id": str(p)}

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
        "object": [_file_ref(p) for p in cmd.inputs],
        "result": [_file_ref(p) for p in cmd.outputs],
    }
    if not completed:
        action["error"] = f"Command exited with code {cmd.exit_code}; see stderr log."
    entities: list[dict[str, Any]] = [action]
    for rel, label in [
        (cmd.sidecar, "invocation record"),
        (cmd.stdout_log, "stdout"),
        (cmd.stderr_log, "stderr"),
    ]:
        if rel:
            entities.append(
                {
                    "@id": rel,
                    "@type": "File",
                    "name": f"{cmd.command_id} {label}",
                    "encodingFormat": "application/json" if rel.endswith(".json") else "text/plain",
                    "about": {"@id": cmd.action_id},
                }
            )
    return entities


def _action_name(cmd: CommandRecord) -> str:
    """Deterministic, unique name derived from the display command and command id."""
    base = cmd.display_command.strip() if cmd.display_command else " ".join(cmd.argv)
    if not base:
        base = cmd.command_id
    # Suffix the command id to guarantee uniqueness when two commands share the same display text.
    return f"{base} [{cmd.command_id}]"


# ---------------------------------------------------------------------------
# File entities (§15.6)
# ---------------------------------------------------------------------------


def build_file_entity(
    plan: Any, max_hash_bytes: int, formal_parameter_id: str | None = None
) -> dict[str, Any]:
    """Return a File or Dataset entity for one ``FilePlan``."""
    from ro_crate_run.files import file_record

    declared = getattr(plan, "declared", {}) or {}
    abs_path: Path = plan.abs_path
    rec = file_record(abs_path, abs_path.parent, max_hash_bytes)
    entity: dict[str, Any] = {
        "@id": plan.file_id,
        "@type": "Dataset" if rec.get("kind") == "directory" else "File",
        "name": os.path.basename(plan.file_id),
        "description": declared.get("description") or declared.get("role") or "Run file",
        "encodingFormat": rec.get("encoding_format"),
        "contentSize": str(rec["content_size"]) if rec.get("content_size") is not None else None,
        "dateModified": rec.get("date_modified"),
    }
    if rec.get("sha256"):
        entity["identifier"] = {
            "@type": "PropertyValue",
            "propertyID": "sha256",
            "value": str(rec["sha256"]).replace("sha256:", ""),
        }
    elif rec.get("hash_status") == "skipped":
        entity["additionalProperty"] = {
            "@type": "PropertyValue",
            "propertyID": "hash-status",
            "value": "not-hashed",
            "description": str(rec.get("hash_skip_reason", "skipped")),
        }
    if formal_parameter_id:
        entity["exampleOfWork"] = {"@id": formal_parameter_id}
    return {k: v for k, v in entity.items() if v is not None}


# ---------------------------------------------------------------------------
# Parameters / FormalParameters (C10)
# ---------------------------------------------------------------------------


def build_parameters(model: RunModel) -> list[dict[str, Any]]:
    """Emit FormalParameter + PropertyValue pairs for each declared run parameter."""
    entities: list[dict[str, Any]] = []
    for parameter in model.parameters:
        name = str(parameter.get("name", "parameter"))
        formal_id = str(parameter.get("formal_parameter") or f"#param/{name}")
        value_id = f"#param-value/{name}"
        entities.append(
            {
                "@id": formal_id,
                "@type": "FormalParameter",
                "name": name,
                "additionalType": parameter.get("type", "Text"),
                "valueRequired": True,
            }
        )
        entities.append(
            {
                "@id": value_id,
                "@type": "PropertyValue",
                "name": name,
                "propertyID": name,
                "value": str(parameter.get("value", "")),
                "exampleOfWork": {"@id": formal_id},
            }
        )
    return entities


def workflow_formal_parameters(
    model: RunModel,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return (FormalParameter entities, path→formal_parameter_id map) for
    workflow/provenance profiles; returns ([], {}) for process profile."""
    if model.selected_profile not in {"workflow", "provenance"} or not model.workflow:
        return [], {}
    wf_path = str(model.workflow.get("path", ""))
    params: list[dict[str, Any]] = []
    path_map: dict[str, str] = {}
    for kind, items in (("input", model.inputs), ("output", model.outputs)):
        for item in items:
            path = str(item.get("path", ""))
            if not path or path == wf_path or item.get("role") in {"workflow-definition", "config"}:
                # SPEC §15.9.7: config-role files are plain File entities only, no FormalParameter.
                continue
            fp_id = f"#formal/{kind}/{os.path.basename(path)}"
            path_map[path] = fp_id
            params.append(
                {
                    "@id": fp_id,
                    "@type": "FormalParameter",
                    "name": item.get("role") or os.path.basename(path),
                    "additionalType": "File",
                    "valueRequired": bool(item.get("required", False)),
                }
            )
    return params, path_map


# ---------------------------------------------------------------------------
# Workflow (C11, C16, §15.7, §15.9)
# ---------------------------------------------------------------------------


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
        "programmingLanguage": model.workflow.get("engine", "workflow"),
    }
    input_refs = [
        {"@id": formal_param_map[str(item.get("path", ""))]}
        for item in model.inputs
        if str(item.get("path", "")) in formal_param_map
    ]
    output_refs = [
        {"@id": formal_param_map[str(item.get("path", ""))]}
        for item in model.outputs
        if str(item.get("path", "")) in formal_param_map
    ]
    if input_refs:
        entity["input"] = input_refs
    if output_refs:
        entity["output"] = output_refs
    if model.steps:
        entity["step"] = [
            {"@id": idmap.entity_for_step(step_id)} for step_id in sorted(model.steps)
        ]
    return [entity]


# ---------------------------------------------------------------------------
# Workflow-level action (§15.9.5)
# ---------------------------------------------------------------------------


def build_workflow_action(
    model: RunModel,
    idmap: IdMap,
    wf_id: str,
    project_dir: os.PathLike[str] | str,
) -> list[dict[str, Any]]:
    """Return a top-level workflow-run CreateAction for workflow/provenance profiles."""
    if not model.workflow or not model.commands:
        return []
    proj = Path(project_dir)
    workflow_status = (
        "http://schema.org/FailedActionStatus"
        if any(c.terminal_status == "failed" for c in model.commands)
        else "http://schema.org/CompletedActionStatus"
    )
    workflow_action_id = idmap.entity_for_event(
        f"workflow-run:{model.run_id}", "workflow-action"
    )

    def _ref(path: str) -> dict[str, str]:
        p = Path(path)
        if p.is_absolute():
            try:
                return {"@id": str(p.resolve().relative_to(proj.resolve()))}
            except ValueError:
                return {"@id": p.as_uri()}
        return {"@id": str(p)}

    wf_path = str(model.workflow.get("path", ""))
    return [
        {
            "@id": workflow_action_id,
            "@type": "CreateAction",
            "name": f"Execute workflow for {model.title}",
            "description": "Workflow-level execution action.",
            "startTime": model.commands[0].started_at,
            "endTime": model.commands[-1].ended_at or model.commands[-1].started_at,
            "actionStatus": {"@id": workflow_status},
            "agent": {"@id": "#actor/rcr"},
            "instrument": {"@id": wf_id},
            "object": [
                _ref(str(item["path"]))
                for item in model.inputs
                if str(item.get("path", "")) != wf_path
            ],
            "result": [_ref(str(item["path"])) for item in model.outputs],
        }
    ]


# ---------------------------------------------------------------------------
# Steps (C11)
# ---------------------------------------------------------------------------


def build_steps(model: RunModel, idmap: IdMap) -> list[dict[str, Any]]:
    """Emit a HowToStep for every step id, plus a ControlAction for steps with
    a mapped command.  Guarantees no dangling step refs from build_workflow."""
    if not model.steps:
        return []
    cmd_by_step: dict[str, CommandRecord] = {}
    for cmd in model.commands:
        if cmd.step_id:
            cmd_by_step.setdefault(cmd.step_id, cmd)
    entities: list[dict[str, Any]] = []
    for step_id in sorted(model.steps):
        step_entity_id = idmap.entity_for_step(step_id)
        howto: dict[str, Any] = {"@id": step_entity_id, "@type": "HowToStep", "name": step_id}
        step_cmd: CommandRecord | None = cmd_by_step.get(step_id)
        if step_cmd and step_cmd.argv:
            howto["workExample"] = {"@id": software_entity_id(os.path.basename(step_cmd.argv[0]))}
        entities.append(howto)
        if step_cmd:
            entities.append(
                {
                    "@id": idmap.entity_for_event(f"control:{step_cmd.command_id}", "control"),
                    "@type": "ControlAction",
                    "instrument": {"@id": step_entity_id},
                    "object": {"@id": step_cmd.action_id},
                }
            )
    return entities


# ---------------------------------------------------------------------------
# Git (C5, §15.12)
# ---------------------------------------------------------------------------


def build_git(model: RunModel) -> list[dict[str, Any]]:
    """Emit a #git/state Thing entity (plus optional diff File entity)."""
    git = model.git or {}
    if not git.get("available"):
        return []
    props: list[dict[str, Any]] = []
    if git.get("branch"):
        props.append({"@type": "PropertyValue", "name": "branch", "value": str(git["branch"])})
    props.append(
        {
            "@type": "PropertyValue",
            "name": "dirty",
            "value": "true" if git.get("status") else "false",
        }
    )
    if git.get("remote"):
        props.append({"@type": "PropertyValue", "name": "remote", "value": str(git["remote"])})
    entity: dict[str, Any] = {
        "@id": "#git/state",
        "@type": "Thing",
        "name": "Git repository state",
        "identifier": git.get("commit"),
        "additionalProperty": props,
    }
    entities: list[dict[str, Any]] = [{k: v for k, v in entity.items() if v is not None}]
    if git.get("diff_file"):
        entities.append(
            {
                "@id": str(git["diff_file"]),
                "@type": "File",
                "name": "git diff",
                "encodingFormat": "text/x-patch",
                "about": {"@id": "#git/state"},
            }
        )
    return entities


# ---------------------------------------------------------------------------
# Environment / Containers / Dependencies (C6, §15.11)
# ---------------------------------------------------------------------------


def build_environment(model: RunModel) -> list[dict[str, Any]]:
    """Emit a PropertyValue entity per allowlisted environment variable."""
    env_vars = (model.environment or {}).get("env_vars", {})
    if not isinstance(env_vars, dict):
        return []
    return [
        {"@id": f"#env/{name}", "@type": "PropertyValue", "name": name, "value": str(value)}
        for name, value in sorted(env_vars.items())
    ]


def build_containers(model: RunModel) -> list[dict[str, Any]]:
    """Emit a ContainerImage entity per observed container."""
    entities: list[dict[str, Any]] = []
    for idx, container in enumerate(model.containers, start=1):
        digest = str(container.get("digest", "")).replace("sha256:", "")
        entity = {
            "@id": f"#container/{idx}",
            "@type": "ContainerImage",
            "registry": container.get("registry"),
            "name": container.get("image"),
            "tag": container.get("tag"),
            "sha256": digest or None,
        }
        entities.append({k: v for k, v in entity.items() if v is not None})
    return entities


def build_dependencies(model: RunModel) -> list[dict[str, Any]]:
    """Emit a File entity per observed dependency lockfile."""
    return [
        {
            "@id": str(dep["path"]),
            "@type": "File",
            "name": os.path.basename(str(dep["path"])),
            "description": f"{dep.get('kind', 'dependency')} lockfile",
        }
        for dep in model.dependencies
    ]


# ---------------------------------------------------------------------------
# Notes & decisions (§15.10.8)
# ---------------------------------------------------------------------------


def build_notes_decisions(model: RunModel) -> list[dict[str, Any]]:
    """Emit CreativeWork entities for public notes and decisions."""
    entities: list[dict[str, Any]] = []
    for idx, note in enumerate(model.notes, start=1):
        if note.get("visibility") == "public":
            entities.append(
                {
                    "@id": f"#note/{idx}",
                    "@type": "CreativeWork",
                    "name": f"Public note {idx}",
                    "text": note.get("text", ""),
                    "about": {"@id": "./"},
                }
            )
    for idx, decision in enumerate(model.decisions, start=1):
        if decision.get("visibility") == "public":
            entity: dict[str, Any] = {
                "@id": f"#decision/{idx}",
                "@type": "CreativeWork",
                "name": f"Decision {idx}",
                "text": decision.get("text", ""),
                "about": {"@id": "./"},
            }
            if decision.get("rationale"):
                entity["description"] = f"Rationale: {decision['rationale']}"
            entities.append(entity)
    return entities


# ---------------------------------------------------------------------------
# ParameterConnection (§15.10.8 MAY)
# ---------------------------------------------------------------------------


def build_parameter_connections(model: RunModel) -> list[dict[str, Any]]:
    """Emit ParameterConnection entities for parameters with a connection spec."""
    entities: list[dict[str, Any]] = []
    for idx, parameter in enumerate(model.parameters, start=1):
        conn = parameter.get("connection")
        if isinstance(conn, dict) and conn.get("source") and conn.get("target"):
            entities.append(
                {
                    "@id": f"#connection/{idx}",
                    "@type": "ParameterConnection",
                    "sourceParameter": {"@id": str(conn["source"])},
                    "targetParameter": {"@id": str(conn["target"])},
                }
            )
    return entities


# ---------------------------------------------------------------------------
# Profile-selection confidence (C15)
# ---------------------------------------------------------------------------


def selection_confidence(model: RunModel) -> str:
    """Return ``'high'``/``'medium'``/``'low'`` based on provenance evidence."""
    if model.workflow and model.steps and model.commands:
        return "high"
    if model.commands or model.workflow:
        return "medium"
    return "low"
