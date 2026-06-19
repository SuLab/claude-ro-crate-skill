from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from filelock import FileLock
from rocrate.rocrate import ROCrate  # type: ignore[import-untyped]

from ro_crate_run import __version__ as _rcr_version
from ro_crate_run.constants import (
    DEFAULT_LICENSE,
    RO_CRATE_CONTEXT,
    RO_CRATE_SPEC_URI,
    WORKFLOW_RUN_CONTEXT,
)
from ro_crate_run.ids import IdMap
from ro_crate_run.journal import EventWriter
from ro_crate_run.models import LastCheckpoint, RunModel, strip_none
from ro_crate_run.state import load_config, load_state, read_events, write_state
from ro_crate_run.time import utc_now
from ro_crate_run.validation.validator import validate_run

from .files import log_should_copy, plan_file_inclusion
from .run_model import build_run_model


def checkpoint(state_dir: Path, requested_profile: str = "auto", *, lock_timeout: float = 30.0) -> int:
    with FileLock(str(Path(state_dir) / "checkpoint.lock"), timeout=lock_timeout):
        return _checkpoint_locked(state_dir, requested_profile)


def _checkpoint_locked(state_dir: Path, requested_profile: str = "auto") -> int:
    from .profiles import enrich_with_adapter, select_profile

    # If an explicit profile is requested, persist it to state first so
    # build_run_model (which reads state.requested_profile) honours it.
    if requested_profile != "auto":
        _pre_state = load_state(state_dir)
        _pre_state.requested_profile = requested_profile
        write_state(state_dir, _pre_state)

    preview_state = load_state(state_dir)
    preview = build_run_model(state_dir, preview_state.sequence)
    enrich_with_adapter(preview, Path(state_dir).parent)
    _record_profile_selection(state_dir, preview, requested_profile)
    state = load_state(state_dir)
    # A3/C6: mark dirty if the materializer version changed since last checkpoint.
    if state.last_checkpoint and state.last_checkpoint.materializer_version not in {None, _rcr_version}:
        state.dirty = True
        write_state(state_dir, state)
    # A3/C6: mark dirty if the profile selection changed since last checkpoint.
    if (
        state.last_checkpoint
        and state.selected_profile != preview.selected_profile
    ):
        state.dirty = True
        write_state(state_dir, state)
    high_water = state.sequence
    writer = EventWriter(state_dir)
    start_event = writer.append(
        "crate.checkpoint.started",
        {"materialized_through_sequence": high_water},
        source_kind="materializer",
    )
    try:
        # C1 (§14.2): validate journal syntax + hash chain BEFORE building the model,
        # so a tampered/corrupt journal is caught before it is processed or written.
        from ro_crate_run.validation.context import build_context
        from ro_crate_run.validation.journal import check_journal

        journal_findings = check_journal(build_context(state_dir, strict=False, public=False))
        if journal_findings:
            raise ValueError(
                "journal integrity check failed: "
                + ", ".join(f.code for f in journal_findings)
            )
        model = build_run_model(state_dir, high_water)
        enrich_with_adapter(model, Path(state_dir).parent)
        write_crate(state_dir, model, published_at=utc_now())
        sel = select_profile(model, requested_profile)
        state = load_state(state_dir)
        state.selected_profile = model.selected_profile
        state.profile_uri = model.profile_uri
        state.profile_confidence = sel.confidence
        write_state(state_dir, state)
        report = validate_run(state_dir, strict=False, public=False, append_event=False)
        complete = writer.append(
            "crate.checkpoint.completed",
            {
                "started_event_id": start_event.event_id,
                "materialized_through_sequence": high_water,
                "validation_status": report.status,
            },
            source_kind="materializer",
        )
        state = load_state(state_dir)
        state.last_checkpoint = LastCheckpoint(
            event_id=complete.event_id,
            timestamp=complete.timestamp,
            event_sequence=complete.sequence,
            materialized_through_sequence=high_water,
            validation_status=report.status,
            materializer_version=_rcr_version,
        )
        state.dirty = report.status == "failed"
        write_state(state_dir, state)
        return 0 if report.status != "failed" else 1
    except Exception as exc:
        writer.append("crate.checkpoint.failed", {"error": str(exc)}, source_kind="materializer")
        raise


def write_crate(state_dir: Path, model: RunModel, *, published_at: Optional[str] = None) -> None:
    from ro_crate_run.materialize import mapping

    published_at = published_at or utc_now()
    cfg = load_config(state_dir)
    project_dir = state_dir.parent
    crate_dir = state_dir / "ro-crate"
    crate_dir.mkdir(parents=True, exist_ok=True)
    id_map = IdMap(state_dir)

    # --- Scaffold: descriptor, root, license, profile ---
    graph: list[dict[str, Any]] = []
    descriptor = {
        "@id": "ro-crate-metadata.json",
        "@type": "CreativeWork",
        "about": {"@id": "./"},
        "conformsTo": {"@id": RO_CRATE_SPEC_URI},
    }
    root: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": model.title,
        "description": model.description,
        "datePublished": published_at,
        "dateCreated": model.created_at,
        "dateModified": model.updated_at,
        "license": {"@id": DEFAULT_LICENSE},
        "conformsTo": [{"@id": model.profile_uri}],
        "hasPart": [],
        "mentions": [],
    }
    graph.extend(
        [
            descriptor,
            root,
            {
                "@id": DEFAULT_LICENSE,
                "@type": "CreativeWork",
                "name": "Creative Commons Attribution 4.0 International",
                "description": "CC BY 4.0",
            },
        ]
    )
    graph.append(
        {
            "@id": model.profile_uri,
            "@type": "Profile",
            "name": f"{model.selected_profile.title()} Run Crate",
            "version": "0.5",
        }
    )

    # --- Actors, software, provenance context ---
    graph.extend(mapping.build_actors(model))
    graph.extend(mapping.build_software(model))
    # Honour file_policy.include_git_diff: capture diff when enabled and tree is dirty.
    _maybe_capture_git_diff(model, cfg, project_dir, crate_dir)
    graph.extend(mapping.build_git(model))
    graph.extend(mapping.build_environment(model))
    graph.extend(mapping.build_containers(model))
    graph.extend(mapping.build_dependencies(model))

    # --- Parameters ---
    param_entities = mapping.build_parameters(model)
    graph.extend(param_entities)
    for e in param_entities:
        root["mentions"].append({"@id": e["@id"]})
    wf_params, formal_param_map = mapping.workflow_formal_parameters(model)
    graph.extend(wf_params)

    # --- Files (declared inputs/outputs + command outputs) ---
    max_hash_bytes = cfg.hash_policy.max_file_size_mb * 1024 * 1024
    plans = {plan.file_id: plan for plan in plan_file_inclusion(model, cfg, project_dir)}
    file_ids: set[str] = set()

    for plan in plans.values():
        fp_id = formal_param_map.get(str(plan.declared.get("path", plan.file_id)))
        entity = mapping.build_file_entity(plan, max_hash_bytes, fp_id)
        graph.append(entity)
        file_ids.add(plan.file_id)
        if plan.included:
            root["hasPart"].append({"@id": plan.file_id})
        if plan.copy:
            _copy_into_crate(plan.abs_path, crate_dir / plan.file_id)

    # --- Workflow (mainEntity) ---
    workflow_entities = mapping.build_workflow(model, id_map)
    graph.extend(workflow_entities)
    if workflow_entities:
        wf_id = workflow_entities[0]["@id"]
        root["mainEntity"] = {"@id": wf_id}
        # A synthesized workflow is an abstract entity (the agent's actions), not a file,
        # so it is referenced via mainEntity only and is not part of the data payload.
        synthetic_wf = bool(model.workflow and model.workflow.get("synthetic"))
        if not synthetic_wf and {"@id": wf_id} not in root["hasPart"]:
            root["hasPart"].append({"@id": wf_id})

    # --- Workflow-level action (workflow/provenance profiles only) ---
    if workflow_entities:
        wf_action_entities = mapping.build_workflow_action(
            model, id_map, workflow_entities[0]["@id"], project_dir
        )
        graph.extend(wf_action_entities)
        for e in wf_action_entities:
            root["mentions"].append({"@id": e["@id"]})

    # --- Steps (HowToStep + ControlAction) ---
    graph.extend(mapping.build_steps(model, id_map))

    # --- Command actions ---
    for command in model.commands:
        entities = mapping.build_command_action(command, id_map, project_dir)
        graph.extend(entities)
        root["mentions"].append({"@id": entities[0]["@id"]})
        # Copy logs/sidecars
        for rel in (command.sidecar, command.stdout_log, command.stderr_log):
            if rel and log_should_copy(rel, project_dir, cfg):
                _copy_into_crate(project_dir / rel, crate_dir / rel)
        # Ensure command outputs appear as file entities even when not in plans
        for output in command.outputs:
            output_id = _file_id(output, project_dir)
            if output_id not in file_ids:
                output_plan = plans.get(output_id)
                if output_plan is not None:
                    fp_id2 = formal_param_map.get(str(output_plan.declared.get("path", output_id)))
                    graph.append(mapping.build_file_entity(output_plan, max_hash_bytes, fp_id2))
                    if output_plan.included:
                        root["hasPart"].append({"@id": output_id})
                    if output_plan.copy:
                        _copy_into_crate(output_plan.abs_path, crate_dir / output_id)
                else:
                    # Fallback: emit a minimal File entity for undeclared outputs.
                    from dataclasses import dataclass as _dataclass

                    @_dataclass
                    class _FallbackPlan:
                        file_id: str
                        abs_path: Path
                        declared: dict  # type: ignore[type-arg]

                    fallback = _FallbackPlan(
                        file_id=output_id,
                        abs_path=project_dir / output,
                        declared={"path": output, "description": "Command output"},
                    )
                    graph.append(mapping.build_file_entity(fallback, max_hash_bytes))
                    root["hasPart"].append({"@id": output_id})
                file_ids.add(output_id)
        # Ensure command inputs referenced as the action's `object` have File entities
        # even when not separately declared via `rcr input` (otherwise the object ref
        # would dangle). Inputs are not forced into hasPart — they are referenced only.
        from dataclasses import dataclass as _dataclass
        for input_path in command.inputs:
            input_id = _file_id(input_path, project_dir)
            if input_id in file_ids or input_id.startswith(
                ("http://", "https://", "urn:", "file:", "#")
            ):
                file_ids.add(input_id)
                continue

            @_dataclass
            class _InputPlan:
                file_id: str
                abs_path: Path
                declared: dict  # type: ignore[type-arg]

            input_plan = _InputPlan(
                file_id=input_id,
                abs_path=project_dir / input_path,
                declared={"path": input_path, "description": "Command input"},
            )
            graph.append(mapping.build_file_entity(input_plan, max_hash_bytes))
            file_ids.add(input_id)

    # --- Agent action families (SPEC §16: the Claude agent's actions ARE the workflow) ---
    agent_action_entities = mapping.build_agent_actions(model, project_dir)
    graph.extend(agent_action_entities)
    for e in agent_action_entities:
        types = e["@type"] if isinstance(e["@type"], list) else [e["@type"]]
        # SoftwareApplication/File are referenced by the actions, not mentioned directly.
        if not any(str(t) in {"SoftwareApplication", "File", "Dataset"} for t in types):
            root["mentions"].append({"@id": e["@id"]})

    # --- Notes, decisions, parameter connections ---
    note_decision = mapping.build_notes_decisions(model)
    graph.extend(note_decision)
    root["mentions"].extend({"@id": e["@id"]} for e in note_decision)
    connections = mapping.build_parameter_connections(model)
    graph.extend(connections)
    root["mentions"].extend({"@id": e["@id"]} for e in connections)

    # --- Event journal (gate on file_policy.include_event_journal) ---
    if cfg.file_policy.include_event_journal:
        journal_src = state_dir / "events.ndjson"
        if journal_src.exists():
            journal_rel = "events.ndjson"
            _copy_into_crate(journal_src, crate_dir / journal_rel)
            graph.append({
                "@id": journal_rel,
                "@type": "File",
                "name": "Event journal",
                "encodingFormat": "application/x-ndjson",
                "about": {"@id": "./"},
            })
            root["hasPart"].append({"@id": journal_rel})

    # --- Write ---
    data = {
        "@context": [RO_CRATE_CONTEXT, WORKFLOW_RUN_CONTEXT],
        "@graph": _dedupe(strip_none(graph)),
    }
    _write_metadata_with_rocrate(crate_dir, data)
    from .summary import run_summary

    (crate_dir / "run-summary.json").write_text(
        json.dumps(run_summary(model), indent=2, sort_keys=True) + "\n"
    )


def _copy_into_crate(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _file_id(path: str, project_dir: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(project_dir.resolve()))
        except ValueError:
            return p.as_uri()
    return str(p)


def _dedupe(graph: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for entity in graph:
        entity_id = str(entity.get("@id"))
        if entity_id in by_id:
            by_id[entity_id].update(entity)
        else:
            by_id[entity_id] = entity
    return [by_id[key] for key in sorted(by_id)]


def _record_profile_selection(state_dir: Path, model: RunModel, requested_profile: str) -> None:
    from .profiles import select_profile

    selection = select_profile(model, requested_profile)
    selections = [
        event
        for event in read_events(state_dir)
        if event.get("event_type") == "workflow.profile.selected"
    ]
    if selections:
        last = selections[-1].get("payload", {})
        if (
            isinstance(last, dict)
            and last.get("selected_profile") == selection.profile
            and last.get("profile_uri") == selection.profile_uri
        ):
            return
    reason = (
        f"requested profile {requested_profile}"
        if requested_profile != "auto"
        else "auto-selected from workflow and step evidence"
    )
    EventWriter(state_dir).append(
        "workflow.profile.selected",
        {
            "selected_profile": selection.profile,
            "profile_uri": selection.profile_uri,
            "reason": reason,
            "confidence": selection.confidence,
            "evidence": selection.evidence,
        },
        source_kind="materializer",
        inferred=requested_profile == "auto",
    )
    state = load_state(state_dir)
    state.profile_confidence = selection.confidence
    write_state(state_dir, state)


def _maybe_capture_git_diff(
    model: RunModel, cfg: Any, project_dir: Path, crate_dir: Path
) -> None:
    """Capture git diff and set model.git['diff_file'] when file_policy.include_git_diff
    permits it.  SPEC §14.4: the flag controls whether git diff output is written."""
    fp = cfg.file_policy
    if fp.include_git_diff == "never":
        return
    git = model.git
    if not isinstance(git, dict) or not git.get("available"):
        return
    if not git.get("status"):  # clean tree — no diff to capture
        return
    # Diff already set (e.g. populated from a previous event)
    if git.get("diff_file"):
        return
    from ro_crate_run.git import capture_diff

    diff_content = capture_diff(project_dir)
    if diff_content is None:
        return
    diff_rel = ".ro-crate-run/git-diff.patch"
    diff_abs = project_dir / diff_rel
    diff_abs.parent.mkdir(parents=True, exist_ok=True)
    diff_abs.write_text(diff_content, encoding="utf-8")
    # Reference the diff relative to the crate root (sibling of ro-crate dir)
    model.git["diff_file"] = diff_rel


def _write_metadata_with_rocrate(crate_dir: Path, data: dict[str, Any]) -> None:
    crate = ROCrate(init=True, version="1.2")
    contexts = data.get("@context", [])
    context_list = [contexts] if isinstance(contexts, str) else list(contexts)
    for context in context_list:
        if context != RO_CRATE_CONTEXT and context not in crate.metadata.extra_contexts:
            crate.metadata.extra_contexts.append(context)
    embedded_entities: dict[str, dict[str, Any]] = {}
    for entity in data["@graph"]:
        crate.add_or_update_jsonld(_rocrate_compatible(dict(entity), embedded_entities))
    for entity in embedded_entities.values():
        crate.add_or_update_jsonld(entity)
    with tempfile.TemporaryDirectory(prefix="rocrate-py-", dir=crate_dir.parent) as tmp:
        crate.write(tmp)
        shutil.copy2(Path(tmp) / "ro-crate-metadata.json", crate_dir / "ro-crate-metadata.json")


def _rocrate_compatible(value: Any, embedded_entities: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, list):
        return [_rocrate_compatible(item, embedded_entities) for item in value]
    if isinstance(value, dict):
        converted = {
            key: _rocrate_compatible(item, embedded_entities) for key, item in value.items()
        }
        if "@type" in converted and "@id" not in converted and "@value" not in converted:
            digest = hashlib.sha256(
                json.dumps(converted, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
            converted["@id"] = f"#embedded/{digest}"
            embedded_entities[str(converted["@id"])] = converted
        return converted
    return value
