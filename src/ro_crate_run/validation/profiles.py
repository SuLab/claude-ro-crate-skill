"""Validation level 3 (profile conformance): the process/workflow/provenance
Run-Crate-profile rules — required outputs, action shape, workflow/FormalParameter
structure, and provenance step/control-action links."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ro_crate_run.constants import (
    ACTION_STATUS_FAILED,
    PROFILES,
    ROOT_DATASET_ID,
)
from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .graphview import is_action, types_of

# Prefix the materializer mints on workflow parameter-value PropertyValues
# (e.g. ``#param-value/<name>``); used to tell those apart from other
# PropertyValue nodes that need no exampleOfWork link.
_PARAM_ID_PREFIX = "#param"


def _finding(code: str, message: str, path: str = "") -> ValidationFinding:
    """Construct an L3 (``profile``) finding; the level is bound here so it is not
    repeated on every emission in this checker."""
    return ValidationFinding("profile", code, message, path)


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
                    _finding("missing_required_output", f"Required output is missing: {declared.get('path')}")
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
            findings.append(_finding("process_no_action", "Process Run Crate requires at least one action or a no-op rationale"))
        else:
            # A process crate with no recorded actions is advisory outside strict mode.
            findings.append(ValidationFinding(
                "reproducibility", "no_actions",
                "Process Run Crate has zero actions and no no-op rationale", severity="warning",
            ))
    for action in exec_actions:
        is_create = any(t in _EXECUTION_ACTION_TYPES for t in types_of(action))
        if is_create and "instrument" not in action:
            findings.append(_finding("action_missing_instrument", f"Creating action {action.get('@id')} missing instrument"))
        for key in ("startTime", "endTime", "actionStatus"):
            if key not in action:
                findings.append(_finding("action_missing_timing", f"Action {action.get('@id')} missing {key}"))
        status = action.get("actionStatus", {})
        if isinstance(status, dict) and status.get("@id") == ACTION_STATUS_FAILED and "error" not in action:
            findings.append(_finding("failed_action_missing_error", f"Failed action {action.get('@id')} missing error"))
    return findings


def _check_workflow(ctx: ValidationContext, entities: dict[Any, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    workflows = [e for e in entities.values() if "ComputationalWorkflow" in types_of(e)]
    if not workflows:
        findings.append(_finding("workflow_missing_entity", "Workflow Run Crate requires a ComputationalWorkflow entity"))
    root = entities.get(ROOT_DATASET_ID, {})
    main_entity = root.get("mainEntity", {})
    main_id = main_entity.get("@id") if isinstance(main_entity, dict) else None
    if not main_id or main_id not in entities or "ComputationalWorkflow" not in types_of(entities.get(main_id, {})):
        findings.append(_finding("workflow_missing_main_entity", "Root mainEntity must point to the ComputationalWorkflow"))
    # L3 check (a): at least one action uses the workflow as instrument
    if main_id:
        wf_instrument_actions = [
            e for e in entities.values()
            if is_action(e)
            and (e.get("instrument") or {}).get("@id") == main_id
        ]
        if not wf_instrument_actions:
            # Structural-quality warning: downgraded from an error outside strict mode.
            findings.append(ValidationFinding(
                "profile", "workflow_no_action_uses_instrument",
                "No action uses the ComputationalWorkflow as instrument", severity="warning",
            ))
    # L3 check (b): FormalParameter entities when workflow declares inputs/outputs
    wf_entity = entities.get(main_id or "", {}) if main_id else {}
    wf_inputs = wf_entity.get("input", []) or []
    wf_outputs = wf_entity.get("output", []) or []
    has_wf_io = bool(wf_inputs or wf_outputs)
    has_formal_params = any("FormalParameter" in types_of(e) for e in entities.values())
    if has_wf_io and not has_formal_params:
        findings.append(ValidationFinding(
            "profile", "workflow_missing_formal_parameters",
            "Workflow declares inputs/outputs but no FormalParameter entities found", severity="warning",
        ))
    # L3 check (c): concrete parameter values use exampleOfWork
    for entity in entities.values():
        if "PropertyValue" not in types_of(entity):
            continue
        if entity.get("exampleOfWork") is None:
            fp_id = entity.get("@id", "")
            # Only flag PropertyValues that look like workflow parameter values (#param-value/...)
            if str(fp_id).startswith(_PARAM_ID_PREFIX):
                findings.append(ValidationFinding(
                    "profile", "parameter_value_missing_exampleOfWork",
                    f"Parameter value {fp_id} missing exampleOfWork link to FormalParameter", severity="warning",
                ))
    return findings


def _check_provenance(ctx: ValidationContext, entities: dict[Any, dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    steps = [e for e in entities.values() if "HowToStep" in types_of(e)]
    if not steps:
        findings.append(_finding("provenance_missing_steps", "Provenance Run Crate requires HowToStep entities"))
    if not any("ControlAction" in types_of(e) for e in entities.values()):
        findings.append(_finding("provenance_missing_control_action", "Provenance Run Crate requires ControlAction links"))
    # Provenance 0.5 MUST (05-provenance-run-crate-05.md line 13): every HowToStep's
    # `workExample` MUST reference the tool (or subworkflow) that implements the step.
    for step in steps:
        if not step.get("workExample"):
            findings.append(
                _finding(
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
                _finding(
                    "workflow_missing_haspart",
                    f"ComputationalWorkflow {workflow.get('@id')} has steps but no hasPart linking orchestrated tools",
                )
            )
    return findings


def _check_root_profile(ctx: ValidationContext, entities: dict[Any, dict[str, Any]]) -> list[ValidationFinding]:
    """The root Data Entity MUST declare conformance to the selected Run-Crate
    profile (via ``conformsTo``). Emitted here, after metadata is confirmed
    present, rather than from the ro_crate checker so it stays a profile-level
    finding alongside the rest of the profile rules.

    Only checked when the root entity exists — a wholly-missing root is reported
    by the ro_crate checker (``root_missing``), which mirrors the original guard
    where this rule ran after that checker's early return on a missing root."""
    root = entities.get(ROOT_DATASET_ID)
    if not root:
        return []
    conforms = root.get("conformsTo", [])
    if isinstance(conforms, dict):
        conforms = [conforms]
    selected_spec = PROFILES.get(ctx.state.selected_profile)
    selected_uri = selected_spec.uri if selected_spec else ""
    if {"@id": ctx.state.profile_uri} not in conforms and {"@id": selected_uri} not in conforms:
        return [_finding("root_missing_profile", "Root missing selected profile conformance")]
    return []


def check_profile(ctx: ValidationContext) -> list[ValidationFinding]:
    findings = _check_required_outputs(ctx)
    if not ctx.metadata:
        return findings
    entities = ctx.entities
    profile = ctx.state.selected_profile
    spec = PROFILES.get(profile)
    findings += _check_root_profile(ctx, entities)
    findings += _check_process(ctx, entities)
    if spec is not None and spec.is_workflow_like:
        findings += _check_workflow(ctx, entities)
    if profile == "provenance":
        findings += _check_provenance(ctx, entities)
    return findings
