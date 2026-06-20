"""Validation level 3 (profile conformance): the process/workflow/provenance
Run-Crate-profile rules — required outputs, action shape, workflow/FormalParameter
structure, and provenance step/control-action links."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ro_crate_run.constants import WORKFLOW_LIKE_PROFILES
from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .graphview import is_action, types_of


def _actions(entities: dict[Any, dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entities.values() if is_action(e)]


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


def _check_process(ctx: ValidationContext, entities: dict[Any, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    actions = _actions(entities)
    # Only count execution actions for the "at least one action" requirement.
    exec_actions = [
        a for a in actions
        if not any(t in _CONTROL_ACTION_TYPES for t in types_of(a))
    ]
    if not exec_actions:
        if ctx.strict:
            findings.append(ValidationFinding("profile", "process_no_action", "Process Run Crate requires at least one action or a no-op rationale"))
        else:
            findings.append(ValidationFinding("reproducibility", "no_actions", "Process Run Crate has zero actions and no no-op rationale"))
    for action in exec_actions:
        is_create = any(t in _EXECUTION_ACTION_TYPES for t in types_of(action))
        if is_create and "instrument" not in action:
            findings.append(ValidationFinding("profile", "action_missing_instrument", f"Creating action {action.get('@id')} missing instrument"))
        for key in ("startTime", "endTime", "actionStatus"):
            if key not in action:
                findings.append(ValidationFinding("profile", "action_missing_timing", f"Action {action.get('@id')} missing {key}"))
        status = action.get("actionStatus", {})
        if isinstance(status, dict) and status.get("@id", "").endswith("FailedActionStatus") and "error" not in action:
            findings.append(ValidationFinding("profile", "failed_action_missing_error", f"Failed action {action.get('@id')} missing error"))
    return findings


def _check_workflow(ctx: ValidationContext, entities: dict[Any, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    workflows = [e for e in entities.values() if "ComputationalWorkflow" in types_of(e)]
    if not workflows:
        findings.append(ValidationFinding("profile", "workflow_missing_entity", "Workflow Run Crate requires a ComputationalWorkflow entity"))
    root = entities.get("./", {})
    main_entity = root.get("mainEntity", {})
    main_id = main_entity.get("@id") if isinstance(main_entity, dict) else None
    if not main_id or main_id not in entities or "ComputationalWorkflow" not in types_of(entities.get(main_id, {})):
        findings.append(ValidationFinding("profile", "workflow_missing_main_entity", "Root mainEntity must point to the ComputationalWorkflow"))
    # L3 check (a): at least one action uses the workflow as instrument
    if main_id:
        wf_instrument_actions = [
            e for e in entities.values()
            if is_action(e)
            and (e.get("instrument") or {}).get("@id") == main_id
        ]
        if not wf_instrument_actions:
            findings.append(ValidationFinding("profile", "workflow_no_action_uses_instrument", "No action uses the ComputationalWorkflow as instrument"))
    # L3 check (b): FormalParameter entities when workflow declares inputs/outputs
    wf_entity = entities.get(main_id or "", {}) if main_id else {}
    wf_inputs = wf_entity.get("input", []) or []
    wf_outputs = wf_entity.get("output", []) or []
    has_wf_io = bool(wf_inputs or wf_outputs)
    has_formal_params = any("FormalParameter" in types_of(e) for e in entities.values())
    if has_wf_io and not has_formal_params:
        findings.append(ValidationFinding("profile", "workflow_missing_formal_parameters", "Workflow declares inputs/outputs but no FormalParameter entities found"))
    # L3 check (c): concrete parameter values use exampleOfWork
    for entity in entities.values():
        if "PropertyValue" not in types_of(entity):
            continue
        if entity.get("exampleOfWork") is None:
            fp_id = entity.get("@id", "")
            # Only flag PropertyValues that look like workflow parameter values (#param-value/...)
            if str(fp_id).startswith("#param"):
                findings.append(ValidationFinding("profile", "parameter_value_missing_exampleOfWork", f"Parameter value {fp_id} missing exampleOfWork link to FormalParameter"))
    return findings


def _check_provenance(ctx: ValidationContext, entities: dict[Any, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    steps = [e for e in entities.values() if "HowToStep" in types_of(e)]
    if not steps:
        findings.append(ValidationFinding("profile", "provenance_missing_steps", "Provenance Run Crate requires HowToStep entities"))
    if not any("ControlAction" in types_of(e) for e in entities.values()):
        findings.append(ValidationFinding("profile", "provenance_missing_control_action", "Provenance Run Crate requires ControlAction links"))
    # Provenance 0.5 MUST (05-provenance-run-crate-05.md line 13): every HowToStep's
    # `workExample` MUST reference the tool (or subworkflow) that implements the step.
    for step in steps:
        if not step.get("workExample"):
            findings.append(
                ValidationFinding(
                    "profile",
                    "step_missing_workexample",
                    f"HowToStep {step.get('@id')} missing workExample (tool implementing the step)",
                )
            )
    # Provenance 0.5 MUST (05-provenance-run-crate-05.md line 9): a ComputationalWorkflow
    # that orchestrates steps MUST link the orchestrated tools via `hasPart`. Flag any
    # provenance-profile workflow that declares `step` but omits a non-empty `hasPart`.
    for workflow in entities.values():
        if "ComputationalWorkflow" not in types_of(workflow):
            continue
        if not workflow.get("step"):
            continue
        if not workflow.get("hasPart"):
            findings.append(
                ValidationFinding(
                    "profile",
                    "workflow_missing_haspart",
                    f"ComputationalWorkflow {workflow.get('@id')} has steps but no hasPart linking orchestrated tools",
                )
            )
    return findings


def check_profile(ctx: ValidationContext) -> list[ValidationFinding]:
    findings = _check_required_outputs(ctx)
    if not ctx.metadata:
        return findings
    entities = ctx.entities
    profile = ctx.state.selected_profile
    findings += _check_process(ctx, entities)
    if profile in WORKFLOW_LIKE_PROFILES:
        findings += _check_workflow(ctx, entities)
    if profile == "provenance":
        findings += _check_provenance(ctx, entities)
    return findings
