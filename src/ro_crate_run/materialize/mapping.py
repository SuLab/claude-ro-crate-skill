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
        # Base workflows.html MUST: a language/engine SoftwareApplication entity carries
        # name + url + version. Supply the engine homepage from a local map and the observed
        # engine version when the model carries one, else the placeholder "unknown".
        actors.append(
            {
                "@id": f"#actor/engine/{engine}",
                "@type": "SoftwareApplication",
                "name": engine,
                "url": _ENGINE_HOMEPAGE.get(engine.lower()),
                "softwareVersion": str(
                    model.workflow.get("version") or model.workflow.get("engine_version") or "unknown"
                ),
            }
        )
    # Strip None-valued fields before returning.
    return [{k: v for k, v in actor.items() if v is not None} for actor in actors]


# Engine homepage map (M5). Used to populate the engine SoftwareApplication `url`.
_ENGINE_HOMEPAGE: dict[str, str] = {
    "cwl": "https://www.commonwl.org/",
    "cwltool": "https://www.commonwl.org/",
    "snakemake": "https://snakemake.github.io/",
    "nextflow": "https://www.nextflow.io/",
    "galaxy": "https://galaxyproject.org/",
    "wdl": "https://openwdl.org/",
}


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


def _content_size(rel: str, project_dir: os.PathLike[str] | str) -> str | None:
    """Return the on-disk byte size (as a str) of a project-relative path, or None.

    Used to populate `contentSize` (base RO-Crate 1.2 SHOULD) on auxiliary File entities
    (command sidecars/logs, git-diff patch, dependency manifests). Absolute paths are
    resolved as-is; relative paths are resolved against the project dir.
    """
    if not rel:
        return None
    p = Path(rel)
    candidate = p if p.is_absolute() else Path(project_dir) / p
    try:
        if candidate.is_file():
            return str(candidate.stat().st_size)
    except OSError:
        return None
    return None


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
            # L8-aux: base 1.2 SHOULD — contentSize on the sidecar/log File entity.
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
# Agent action families (SPEC §16: the agent's own actions ARE the workflow)
# ---------------------------------------------------------------------------


def _relative_id(path: str, project_dir: os.PathLike[str] | str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(Path(project_dir).resolve()))
        except ValueError:
            return p.as_uri()
    return str(p)


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
        rel = _relative_id(path, project_dir)
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
        action: dict[str, Any] = {
            "@id": f"#file-action/{fa.get('sequence')}",
            "@type": _FILE_OP_TYPE.get(op, "UpdateAction"),
            "name": f"{tool} {os.path.basename(rel)}",
            "description": f"Claude agent {op} {rel} via the {tool} tool.",
            "startTime": fa.get("timestamp"),
            "endTime": fa.get("timestamp"),
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
            "agent": {"@id": "#actor/claude-code"},
            "instrument": {"@id": tool_id},
        }
        ref = {"@id": rel}
        if op == "deleted":
            action["object"] = [ref]
        else:
            action["result"] = [ref]
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
        entities.append({
            "@id": f"#raw-command/{rc.get('sequence')}",
            "@type": "CreateAction",
            "name": command[:100],
            "description": "Raw shell command run by the agent outside rcr run.",
            "startTime": rc.get("timestamp"),
            "endTime": rc.get("timestamp"),
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
            "agent": {"@id": "#actor/claude-code"},
            "instrument": {"@id": tool_id},
            # L4: Process 0.5 — object MAY. rcr cannot infer the outputs of an unwrapped bash
            # command (so result is intentionally absent), but the command operates on the
            # crate's root dataset, so reference it via `object` to improve the SHOULD-quality.
            "object": [{"@id": "./"}],
        })
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
        entities.append({
            "@id": f"#subagent/{s.get('sequence')}",
            # M6: OrganizeAction is reserved (Provenance 0.5) for the engine-orchestration
            # hierarchy (instrument=engine, object=ControlActions, result=workflow CreateAction).
            # A subagent dispatch has none of those, so it is a generic Action.
            "@type": "Action",
            "name": f"Dispatch subagent {s.get('subagent_type') or tid}",
            "description": str(s.get("description") or "Subagent task dispatched by the agent."),
            "startTime": s.get("timestamp"),
            "endTime": s.get("end", s.get("timestamp")),
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
            "agent": {"@id": "#actor/claude-code"},
        })
    return entities


def build_blocked_actions(model: RunModel) -> list[dict[str, Any]]:
    """Emit a FailedActionStatus Action for each blocked tool call / denied permission."""
    entities: list[dict[str, Any]] = []
    for b in model.blocked_actions:
        reason = str(b.get("reason") or "blocked")
        label = "Failed" if b.get("kind") == "tool-failed" else "Blocked"
        entities.append({
            "@id": f"#blocked/{b.get('sequence')}",
            "@type": "Action",
            "name": f"{label}: {b.get('tool_name') or b.get('kind') or 'action'}",
            "description": reason,
            "startTime": b.get("timestamp"),
            "endTime": b.get("timestamp"),
            "actionStatus": {"@id": "http://schema.org/FailedActionStatus"},
            "error": reason,
            "agent": {"@id": "#actor/claude-code"},
        })
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
        entities.append({
            "@id": f"#tool-use/{name}",
            "@type": "Action",
            "name": f"Used {name} ({count}x)",
            "description": f"The agent used the {name} tool {count} time(s).",
            "startTime": first_ts.get(name),
            "endTime": last_ts.get(name),
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
            "agent": {"@id": "#actor/claude-code"},
        })
    return entities


def build_housekeeping(model: RunModel) -> list[dict[str, Any]]:
    """Emit an Action for each housekeeping event (cwd change, worktree, compaction)."""
    entities: list[dict[str, Any]] = []
    for h in model.housekeeping:
        event = str(h.get("event", ""))
        detail = str(h.get("detail", ""))
        entities.append({
            "@id": f"#housekeeping/{h.get('sequence')}",
            "@type": "Action",
            "name": event.replace(".", " ").strip() or "housekeeping",
            "description": f"{event}{': ' + detail if detail else ''}",
            "startTime": h.get("timestamp"),
            "endTime": h.get("timestamp"),
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
            "agent": {"@id": "#actor/claude-code"},
        })
    return entities


def build_results(model: RunModel) -> list[dict[str, Any]]:
    """Emit an AssessAction for each human accept/reject of a result."""
    entities: list[dict[str, Any]] = []
    for idx, r in enumerate(model.results, start=1):
        accepted = bool(r.get("accepted"))
        status = (
            "http://schema.org/CompletedActionStatus"
            if accepted
            else "http://schema.org/FailedActionStatus"
        )
        entity: dict[str, Any] = {
            "@id": f"#result/{idx}",
            "@type": "AssessAction",
            "name": "Accepted result" if accepted else "Rejected result",
            "description": str(r.get("text", "")),
            "startTime": r.get("timestamp"),
            "endTime": r.get("timestamp"),
            "actionStatus": {"@id": status},
            "agent": {"@id": "#actor/human"},
            "object": {"@id": "./"},
        }
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
        action_status = (
            "http://schema.org/CompletedActionStatus"
            if status == "completed"
            else "http://schema.org/ActiveActionStatus"
        )
        entities.append({
            "@id": f"#phase/{idx}",
            # M6: OrganizeAction is reserved (Provenance 0.5) for engine orchestration; a
            # human work-phase grouping is a generic Action.
            "@type": "Action",
            "name": f"Phase: {name}",
            "description": f"Project phase {name!r} ({status or 'started'}).",
            "startTime": phase.get("timestamp"),
            "endTime": phase.get("end_timestamp") or phase.get("timestamp"),
            "actionStatus": {"@id": action_status},
            "agent": {"@id": "#actor/human"},
        })
    return entities


def build_agent_actions(
    model: RunModel,
    project_dir: os.PathLike[str] | str,
    emitted_file_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate every agent-action family into crate entities (SPEC §16)."""
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


# ---------------------------------------------------------------------------
# File entities (§15.6)
# ---------------------------------------------------------------------------


def build_file_entity(
    plan: Any, max_hash_bytes: int, formal_parameter_id: str | None = None
) -> dict[str, Any]:
    """Return a File or Dataset entity for one ``FilePlan``."""
    from ro_crate_run.files import file_record

    declared = getattr(plan, "declared", {}) or {}
    if getattr(plan, "sensitive", False):
        # Never read content (no hash, no size) — only a content-free reference.
        sensitive_entity: dict[str, Any] = {
            "@id": plan.file_id,
            "@type": "File",
            "name": os.path.basename(plan.file_id),
            "description": declared.get("description") or "Sensitive file (never captured)",
            "additionalProperty": {
                "@type": "PropertyValue",
                "propertyID": "capture-status",
                "value": "not-captured",
                "description": "sensitive file; never read, hashed, or copied",
            },
        }
        if formal_parameter_id:
            sensitive_entity["exampleOfWork"] = {"@id": formal_parameter_id}
        return sensitive_entity
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
    add_props: list[dict[str, Any]] = []
    if rec.get("sha256"):
        entity["identifier"] = {
            "@type": "PropertyValue",
            "propertyID": "sha256",
            "value": str(rec["sha256"]).replace("sha256:", ""),
        }
    elif rec.get("hash_status") == "skipped":
        add_props.append({
            "@type": "PropertyValue",
            "propertyID": "hash-status",
            "value": "not-hashed",
            "description": str(rec.get("hash_skip_reason", "skipped")),
        })
    # Materialize the declared existence classification (observed-local/remote, generated,
    # expected, missing, declared-only) so a crate consumer can tell an observed input from
    # an expected-but-absent output — otherwise this lives only in state.json (SPEC §11).
    existence = declared.get("existence")
    if existence:
        add_props.append({
            "@type": "PropertyValue",
            "propertyID": "existence",
            "value": str(existence),
        })
    if add_props:
        # Single dict when one (keeps the established hash-status shape), list when several.
        entity["additionalProperty"] = add_props[0] if len(add_props) == 1 else add_props
    if formal_parameter_id:
        entity["exampleOfWork"] = {"@id": formal_parameter_id}
    return {k: v for k, v in entity.items() if v is not None}


# ---------------------------------------------------------------------------
# Parameters / FormalParameters (C10)
# ---------------------------------------------------------------------------


# L2: Bioschemas FormalParameter profile. WfRC 0.5 SHOULD — each FormalParameter
# SHOULD carry conformsTo → this profile permalink.
_FORMAL_PARAMETER_PROFILE = "https://bioschemas.org/profiles/FormalParameter/1.0-RELEASE"


def _formal_parameter_profile_entity() -> dict[str, Any]:
    """The contextual Profile entity the FormalParameter conformsTo refs point at."""
    return {
        "@id": _FORMAL_PARAMETER_PROFILE,
        "@type": ["CreativeWork", "Profile"],
        "name": "Bioschemas FormalParameter profile 1.0-RELEASE",
    }


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
                # L2: WfRC 0.5 SHOULD — conformsTo the Bioschemas FormalParameter profile.
                "conformsTo": {"@id": _FORMAL_PARAMETER_PROFILE},
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
    if model.parameters:
        # Emit the referenced Profile contextual entity once so the conformsTo ref resolves.
        entities.append(_formal_parameter_profile_entity())
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
                    # L2: WfRC 0.5 SHOULD — conformsTo the Bioschemas FormalParameter profile.
                    "conformsTo": {"@id": _FORMAL_PARAMETER_PROFILE},
                }
            )
    if params:
        params.append(_formal_parameter_profile_entity())
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
        # Reference the engine SoftwareApplication (#actor/engine/<engine>) build_actors emits,
        # so it is not an orphan; fall back to a plain string for an unknown engine.
        "programmingLanguage": (
            {"@id": f"#actor/engine/{model.workflow['engine']}"}
            if model.workflow.get("engine") and model.workflow["engine"] != "unknown"
            else model.workflow.get("engine", "workflow")
        ),
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
    # H4: Provenance 0.5 MUST — the ComputationalWorkflow's hasPart references the @ids of
    # the orchestrated tools (the SoftwareApplications the steps invoke + the engine). Every
    # ref MUST resolve, so we only list ids that build_software / build_actors actually emit.
    tool_ids = _orchestrated_tool_ids(model)
    if tool_ids:
        entity["hasPart"] = [{"@id": tid} for tid in tool_ids]
    return [entity]


def _orchestrated_tool_ids(model: RunModel) -> list[str]:
    """Return the ordered, de-duplicated @ids of tools orchestrated by the workflow (H4).

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
        _add(f"#actor/engine/{engine}")
    return ids


# ---------------------------------------------------------------------------
# Workflow-level action (§15.9.5)
# ---------------------------------------------------------------------------


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
    if not (model.commands or model.file_actions or model.raw_commands):
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

    if model.commands:
        start_time = model.commands[0].started_at
        end_time = model.commands[-1].ended_at or model.commands[-1].started_at
        # `rcr run` work is recorded by the rcr materializer.
        agent_id = "#actor/rcr"
    else:
        # Edit-only session: the Claude agent performed the work directly.
        stamps = [
            str(item.get("timestamp", ""))
            for item in (*model.file_actions, *model.raw_commands)
            if item.get("timestamp")
        ]
        start_time = min(stamps) if stamps else model.created_at
        end_time = max(stamps) if stamps else model.updated_at
        agent_id = "#actor/claude-code"

    wf_path = str(model.workflow.get("path", ""))
    action: dict[str, Any] = {
        "@id": workflow_action_id,
        "@type": "CreateAction",
        "name": f"Execute workflow for {model.title}",
        "description": "Workflow-level execution action.",
        "startTime": start_time,
        "endTime": end_time,
        "actionStatus": {"@id": workflow_status},
        "agent": {"@id": agent_id},
        "instrument": {"@id": wf_id},
        "object": [
            _ref(str(item["path"]))
            for item in model.inputs
            if str(item.get("path", "")) != wf_path
        ],
        "result": [_ref(str(item["path"])) for item in model.outputs],
    }
    if workflow_status.endswith("FailedActionStatus"):
        # L3: a FailedActionStatus action must carry an error.
        action["error"] = "One or more commands in the workflow failed; see the command actions."
    return [action]


# ---------------------------------------------------------------------------
# Steps (C11)
# ---------------------------------------------------------------------------


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
            "instrument": {"@id": step_id},
            "object": {"@id": action_id},
        })
        step_refs.append({"@id": step_id})
    return entities, step_refs


_STEP_STATUS_URI = {
    "started": "http://schema.org/ActiveActionStatus",
    "completed": "http://schema.org/CompletedActionStatus",
    "failed": "http://schema.org/FailedActionStatus",
    "skipped": "http://schema.org/FailedActionStatus",
}


def _step_fallback_workexample(model: RunModel) -> str | None:
    """Return the @id used as a command-less step's `workExample` (H3).

    Prefer the workflow engine SoftwareApplication (`#actor/engine/<engine>`, emitted by
    build_actors when the engine is known); otherwise fall back to the workflow entity
    itself (`model.workflow["path"]`, always present when steps exist). Both refs resolve.
    """
    wf = model.workflow or {}
    engine = wf.get("engine")
    if engine and engine != "unknown":
        return f"#actor/engine/{engine}"
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
    # H3: workExample MUST be set on EVERY HowToStep (Provenance 0.5 MUST). A command-less
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
            howto["workExample"] = {"@id": software_entity_id(os.path.basename(step_cmd.argv[0]))}
        elif fallback_workexample is not None:
            howto["workExample"] = {"@id": fallback_workexample}
        entities.append(howto)
        if step_cmd:
            entities.append(
                {
                    "@id": idmap.entity_for_event(f"control:{step_cmd.command_id}", "control"),
                    "@type": "ControlAction",
                    "instrument": {"@id": step_entity_id},
                    "object": {"@id": step_cmd.action_id},
                    "actionStatus": {
                        "@id": _STEP_STATUS_URI.get(
                            status, "http://schema.org/CompletedActionStatus"
                        )
                    },
                }
            )
    return entities


# ---------------------------------------------------------------------------
# Git (C5, §15.12)
# ---------------------------------------------------------------------------


def build_git(
    model: RunModel, project_dir: os.PathLike[str] | str | None = None
) -> list[dict[str, Any]]:
    """Emit a #git/state Thing entity (plus optional diff File entity).

    ``project_dir`` (optional) is used only to compute ``contentSize`` on the git-diff
    File entity (L8-aux, base 1.2 SHOULD).
    """
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
        diff_entity: dict[str, Any] = {
            "@id": str(git["diff_file"]),
            "@type": "File",
            "name": "git diff",
            "encodingFormat": "text/x-patch",
            "about": {"@id": "#git/state"},
        }
        if project_dir is not None:
            size = _content_size(str(git["diff_file"]), project_dir)
            if size is not None:
                diff_entity["contentSize"] = size
        entities.append(diff_entity)
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


_DOCKER_IMAGE_TYPE = "https://w3id.org/ro/terms/workflow-run#DockerImage"
_SIF_IMAGE_TYPE = "https://w3id.org/ro/terms/workflow-run#SIFImage"


def _container_additional_type(registry: str, image: str, tag: str) -> str:
    """Derive the ContainerImage additionalType URI from the registry/ref (M7).

    SIF / Singularity / Apptainer references → SIFImage; everything else (OCI/Docker
    registries: docker.io, ghcr.io, quay.io, registry.*, or an unqualified default) → DockerImage.
    The terms are vendored in assets/contexts/workflow-run.jsonld.
    """
    blob = " ".join((registry, image, tag)).lower()
    if image.lower().endswith(".sif") or "singularity" in blob or "apptainer" in blob:
        return _SIF_IMAGE_TYPE
    return _DOCKER_IMAGE_TYPE


def build_containers(model: RunModel) -> list[dict[str, Any]]:
    """Emit a ContainerImage entity per observed container."""
    entities: list[dict[str, Any]] = []
    for idx, container in enumerate(model.containers, start=1):
        digest = str(container.get("digest", "")).replace("sha256:", "")
        entity = {
            "@id": f"#container/{idx}",
            "@type": "ContainerImage",
            # M7: Process/Workflow 0.5 SHOULD — ContainerImage SHOULD list additionalType
            # (a workflow-run namespace URI) alongside registry + name.
            "additionalType": {
                "@id": _container_additional_type(
                    str(container.get("registry", "")),
                    str(container.get("image", "")),
                    str(container.get("tag", "")),
                )
            },
            "registry": container.get("registry"),
            "name": container.get("image"),
            "tag": container.get("tag"),
            "sha256": digest or None,
        }
        entities.append({k: v for k, v in entity.items() if v is not None})
    return entities


def build_dependencies(
    model: RunModel, project_dir: os.PathLike[str] | str | None = None
) -> list[dict[str, Any]]:
    """Emit a File entity per observed dependency lockfile / manifest.

    Carries the recorded sha256 so the manifest is verifiable (the digest is captured at
    scan time but was previously dropped), and gives it a sensible description.
    ``project_dir`` (optional) is used only to populate ``contentSize`` (L8-aux, base 1.2 SHOULD).
    """
    entities: list[dict[str, Any]] = []
    for dep in model.dependencies:
        name = os.path.basename(str(dep["path"]))
        kind = str(dep.get("kind", "lockfile")) or "lockfile"
        entity: dict[str, Any] = {
            "@id": str(dep["path"]),
            "@type": "File",
            "name": name,
            "description": f"Dependency manifest ({kind})",
        }
        digest = str(dep.get("file_record", "")).replace("sha256:", "")
        if digest:
            entity["identifier"] = {
                "@type": "PropertyValue",
                "propertyID": "sha256",
                "value": digest,
            }
        if project_dir is not None:
            size = _content_size(str(dep["path"]), project_dir)
            if size is not None:
                entity["contentSize"] = size
        entities.append(entity)
    return entities


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


