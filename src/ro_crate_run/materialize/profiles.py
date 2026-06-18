from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ro_crate_run.constants import PROFILE_URIS
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
    if run_model.commands:
        evidence.append({"kind": "commands", "count": len(run_model.commands)})
    if requested in {"process", "workflow", "provenance"}:
        return ProfileSelection(requested, PROFILE_URIS[requested], "high", evidence)
    # Provenance requires step-level EXECUTION evidence (SPEC §16.3), not merely
    # step definitions discovered from a workflow file (status "identified").
    executed_steps = any(
        step.get("status") not in (None, "identified") for step in run_model.steps.values()
    ) or any(command.step_id for command in run_model.commands)
    if run_model.workflow and executed_steps:
        profile, confidence = "provenance", "high"
    elif run_model.workflow:
        profile, confidence = "workflow", "high" if run_model.steps else "medium"
    else:
        profile, confidence = "process", "high" if run_model.commands else "low"
    return ProfileSelection(profile, PROFILE_URIS[profile], confidence, evidence)


def enrich_with_adapter(model: RunModel, project_dir: Path) -> None:
    """Use workflow adapters to confirm engine and discover steps from the
    workflow definition, so Provenance promotion has step evidence even when
    no explicit ``rcr step`` events were recorded."""
    if not model.workflow:
        return
    raw = str(model.workflow.get("path", ""))
    wf_path = Path(raw)
    if not wf_path.is_absolute():
        wf_path = project_dir / wf_path
    if not wf_path.exists():
        return
    from ro_crate_run import adapters

    detected = adapters.detect_engine(wf_path)
    if detected is None:
        return
    model.workflow["engine"] = str(detected["engine"])
    for step_id in adapters.extract_steps(wf_path):
        model.steps.setdefault(step_id, {"step_id": step_id, "status": "identified"})
