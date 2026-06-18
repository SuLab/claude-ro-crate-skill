from __future__ import annotations

from pathlib import Path
from typing import Any

from ro_crate_run.models import ValidationFinding

from .context import ValidationContext


def _entities(ctx: ValidationContext) -> dict[str, dict[str, Any]]:
    if not ctx.metadata:
        return {}
    return {e.get("@id"): e for e in ctx.metadata.get("@graph", [])}


def _types(entity: dict[str, Any]) -> list[str]:
    t = entity.get("@type", [])
    return t if isinstance(t, list) else [t]


def _actions(entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entities.values() if any(str(t).endswith("Action") for t in _types(e))]


def _check_required_outputs(ctx: ValidationContext) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for declared in ctx.state.declared_outputs:
        if declared.get("required"):
            p = Path(str(declared.get("path", "")))
            actual = p if p.is_absolute() else ctx.state_dir.parent / p
            if not actual.exists():
                findings.append(
                    ValidationFinding("profile", "missing_required_output", f"Required output is missing: {declared.get('path')}")
                )
    return findings


_EXECUTION_ACTION_TYPES = {"CreateAction", "UpdateAction", "ActivateAction"}
_CONTROL_ACTION_TYPES = {"ControlAction", "OrchestrationAction"}


def _check_process(ctx: ValidationContext, entities: dict[str, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    actions = _actions(entities)
    # Only count execution actions for the "at least one action" requirement.
    exec_actions = [
        a for a in actions
        if not any(t in _CONTROL_ACTION_TYPES for t in _types(a))
    ]
    if not exec_actions:
        if ctx.strict:
            findings.append(ValidationFinding("profile", "process_no_action", "Process Run Crate requires at least one action or a no-op rationale"))
        else:
            findings.append(ValidationFinding("reproducibility", "no_actions", "Process Run Crate has zero actions and no no-op rationale"))
    for action in exec_actions:
        is_create = any(t in _EXECUTION_ACTION_TYPES for t in _types(action))
        if is_create and "instrument" not in action:
            findings.append(ValidationFinding("profile", "action_missing_instrument", f"Creating action {action.get('@id')} missing instrument"))
        for key in ("startTime", "endTime", "actionStatus"):
            if key not in action:
                findings.append(ValidationFinding("profile", "action_missing_timing", f"Action {action.get('@id')} missing {key}"))
        status = action.get("actionStatus", {})
        if isinstance(status, dict) and status.get("@id", "").endswith("FailedActionStatus") and "error" not in action:
            findings.append(ValidationFinding("profile", "failed_action_missing_error", f"Failed action {action.get('@id')} missing error"))
    return findings


def _check_workflow(ctx: ValidationContext, entities: dict[str, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    workflows = [e for e in entities.values() if "ComputationalWorkflow" in _types(e)]
    if not workflows:
        findings.append(ValidationFinding("profile", "workflow_missing_entity", "Workflow Run Crate requires a ComputationalWorkflow entity"))
    root = entities.get("./", {})
    main_entity = root.get("mainEntity", {})
    main_id = main_entity.get("@id") if isinstance(main_entity, dict) else None
    if not main_id or main_id not in entities or "ComputationalWorkflow" not in _types(entities.get(main_id, {})):
        findings.append(ValidationFinding("profile", "workflow_missing_main_entity", "Root mainEntity must point to the ComputationalWorkflow"))
    # L3 check (a): at least one action uses the workflow as instrument
    if main_id:
        wf_instrument_actions = [
            e for e in entities.values()
            if any(t.endswith("Action") for t in _types(e))
            and (e.get("instrument") or {}).get("@id") == main_id
        ]
        if not wf_instrument_actions:
            findings.append(ValidationFinding("profile", "workflow_no_action_uses_instrument", "No action uses the ComputationalWorkflow as instrument"))
    # L3 check (b): FormalParameter entities when workflow declares inputs/outputs
    wf_entity = entities.get(main_id or "", {}) if main_id else {}
    wf_inputs = wf_entity.get("input", []) or []
    wf_outputs = wf_entity.get("output", []) or []
    has_wf_io = bool(wf_inputs or wf_outputs)
    has_formal_params = any("FormalParameter" in _types(e) for e in entities.values())
    if has_wf_io and not has_formal_params:
        findings.append(ValidationFinding("profile", "workflow_missing_formal_parameters", "Workflow declares inputs/outputs but no FormalParameter entities found"))
    # L3 check (c): concrete parameter values use exampleOfWork
    for entity in entities.values():
        if "PropertyValue" not in _types(entity):
            continue
        if entity.get("exampleOfWork") is None:
            fp_id = entity.get("@id", "")
            # Only flag PropertyValues that look like workflow parameter values (#param-value/...)
            if str(fp_id).startswith("#param"):
                findings.append(ValidationFinding("profile", "parameter_value_missing_exampleOfWork", f"Parameter value {fp_id} missing exampleOfWork link to FormalParameter"))
    return findings


def _check_provenance(ctx: ValidationContext, entities: dict[str, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if not any("HowToStep" in _types(e) for e in entities.values()):
        findings.append(ValidationFinding("profile", "provenance_missing_steps", "Provenance Run Crate requires HowToStep entities"))
    if not any("ControlAction" in _types(e) for e in entities.values()):
        findings.append(ValidationFinding("profile", "provenance_missing_control_action", "Provenance Run Crate requires ControlAction links"))
    return findings


def check_profile(ctx: ValidationContext) -> list[ValidationFinding]:
    findings = _check_required_outputs(ctx)
    if not ctx.metadata:
        return findings
    entities = _entities(ctx)
    profile = ctx.state.selected_profile
    findings += _check_process(ctx, entities)
    if profile in {"workflow", "provenance"}:
        findings += _check_workflow(ctx, entities)
    if profile == "provenance":
        findings += _check_provenance(ctx, entities)
    return findings
