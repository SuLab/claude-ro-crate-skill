from __future__ import annotations

from ro_crate_run.materialize.profiles import ProfileSelection, select_profile
from ro_crate_run.models import CommandRecord, RunModel


def _model(**kw) -> RunModel:  # type: ignore[no-untyped-def]
    base: dict = dict(
        run_id="run_x",
        title="t",
        description="d",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
        selected_profile="process",
        requested_profile="auto",
        profile_uri="",
        mode="monitored",
    )
    base.update(kw)
    return RunModel(**base)


def test_auto_selects_process_when_no_workflow() -> None:
    cmd = CommandRecord("c", "e", "a", [], "", "", "")
    sel = select_profile(_model(commands=[cmd]), "auto")
    assert sel.profile == "process"
    assert sel.profile_uri == "https://w3id.org/ro/wfrun/process/0.5"
    assert sel.confidence in {"low", "medium", "high"}


def test_auto_selects_workflow_when_workflow_only() -> None:
    sel = select_profile(_model(workflow={"path": "Snakefile"}), "auto")
    assert sel.profile == "workflow"
    assert sel.confidence == "medium"


def test_auto_selects_provenance_when_workflow_and_steps() -> None:
    sel = select_profile(
        _model(workflow={"path": "wf.cwl"}, steps={"s1": {"status": "completed"}}),
        "auto",
    )
    assert sel.profile == "provenance"
    assert sel.confidence == "high"
    assert any(e["kind"] == "steps" for e in sel.evidence)


def test_explicit_request_overrides_evidence() -> None:
    sel = select_profile(
        _model(workflow={"path": "wf.cwl"}, steps={"s1": {}}),
        "process",
    )
    assert sel.profile == "process"
    assert sel.confidence == "high"


def test_profile_selection_is_dataclass() -> None:
    sel = ProfileSelection("process", "https://w3id.org/ro/wfrun/process/0.5", "high", [])
    assert sel.profile == "process"
    assert sel.profile_uri == "https://w3id.org/ro/wfrun/process/0.5"
    assert sel.confidence == "high"
    assert sel.evidence == []
