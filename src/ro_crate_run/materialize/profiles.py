"""Profile selection (process/workflow/provenance) and synthesis of the agent-as-workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ro_crate_run.constants import PROFILE_URIS, WORKFLOW_LIKE_PROFILES
from ro_crate_run.models import RunModel


@dataclass
class ProfileSelection:
    profile: str
    profile_uri: str
    confidence: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


def select_profile(run_model: RunModel, requested: str = "auto") -> ProfileSelection:
    evidence: list[dict[str, Any]] = []
    if run_model.workflow:
        evidence.append({"kind": "workflow", "path": run_model.workflow.get("path")})
    if run_model.steps:
        evidence.append({"kind": "steps", "count": len(run_model.steps)})
    if run_model.phases:
        evidence.append({"kind": "phases", "count": len(run_model.phases)})
    if run_model.commands:
        evidence.append({"kind": "commands", "count": len(run_model.commands)})
    agent_actions = (
        len(run_model.file_actions) + len(run_model.raw_commands) + len(run_model.subagents)
    )
    if agent_actions:
        evidence.append({"kind": "agent_actions", "count": agent_actions})
    if requested in PROFILE_URIS:
        return ProfileSelection(requested, PROFILE_URIS[requested], "high", evidence)
    # The actions taken by the Claude Code agent ARE the workflow (SPEC §16): promotion
    # is driven by how structured that work is, independent of any external workflow-system
    # definition file.
    #   - explicit per-step execution evidence (`rcr step` / `rcr run --step`)  -> provenance
    #   - structured work (phases, or more than one command) or an external file -> workflow
    #   - a single, flat command run                                            -> process
    executed_steps = any(
        step.get("status") not in (None, "identified") for step in run_model.steps.values()
    ) or any(command.step_id for command in run_model.commands)
    # The agent's file edits and other actions count as structured work, so edit-driven
    # sessions (even with zero rcr-run commands) are treated as a workflow.
    total_actions = len(run_model.commands) + agent_actions
    structured = bool(run_model.phases) or total_actions > 1 or bool(run_model.file_actions)
    if executed_steps:
        profile, confidence = "provenance", "high"
    elif run_model.workflow:
        profile, confidence = "workflow", "high" if run_model.steps else "medium"
    elif structured:
        profile, confidence = "workflow", "medium"
    elif run_model.commands:
        profile, confidence = "process", "high"
    else:
        profile, confidence = "process", "low"
    return ProfileSelection(profile, PROFILE_URIS[profile], confidence, evidence)


def synthesize_workflow(model: RunModel) -> None:
    """Represent the agent's own actions as the workflow (SPEC §16).

    When the Workflow or Provenance profile is selected but no external workflow
    definition file was declared, synthesize an (abstract) ComputationalWorkflow
    standing for the Claude Code agent's run, so the crate conforms to the profile
    without requiring a workflow-system file. An external definition, when present,
    is used as-is (optional enrichment) and is never overwritten here.
    """
    if model.selected_profile not in WORKFLOW_LIKE_PROFILES:
        return
    if model.workflow:
        return
    model.workflow = {
        "path": "#workflow/agent-actions",
        "name": f"{model.title} — agent actions",
        "engine": "claude-code",
        "synthetic": True,
    }


def apply_selection(model: RunModel, requested: str | None = None) -> ProfileSelection:
    """Run profile selection and record its result on the model.

    Writes ``selected_profile``/``profile_uri``/``profile_confidence`` and the
    stringified ``profile_evidence`` so downstream consumers read the decision
    rather than recomputing it. Returns the selection for callers that need it.
    """
    selection = select_profile(model, requested or model.requested_profile)
    model.selected_profile = selection.profile
    model.profile_uri = selection.profile_uri
    model.profile_confidence = selection.confidence
    model.profile_evidence = [str(item) for item in selection.evidence]
    return selection


def enrich_with_adapter(model: RunModel, project_dir: Path) -> None:
    """Use workflow adapters to confirm engine and discover steps from the
    workflow definition, so Provenance promotion has step evidence even when
    no explicit ``rcr step`` events were recorded.

    Adapter-discovered steps mutate ``model.steps``, so profile selection is
    re-run afterwards and recorded on the model: the recorded decision reflects
    the post-enrichment step evidence.
    """
    if model.workflow:
        raw = str(model.workflow.get("path", ""))
        wf_path = Path(raw)
        if not wf_path.is_absolute():
            wf_path = project_dir / wf_path
        if wf_path.exists():
            from ro_crate_run import adapters

            detected = adapters.detect_engine(wf_path)
            if detected is not None:
                model.workflow["engine"] = str(detected["engine"])
                for step_id in adapters.extract_steps(wf_path):
                    model.steps.setdefault(
                        step_id, {"step_id": step_id, "status": "identified"}
                    )
    apply_selection(model)
