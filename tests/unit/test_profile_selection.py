from __future__ import annotations

from ro_crate_run.materialize.profiles import (
    ProfileSelection,
    select_profile,
    synthesize_workflow,
)
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


def _cmd(cid: str, **kw):  # type: ignore[no-untyped-def]
    return CommandRecord(cid, f"e-{cid}", f"a-{cid}", [], "", "", "", **kw)


def test_auto_multiple_commands_promote_to_workflow() -> None:
    # The agent's actions ARE the workflow: structured (multi-command) work, even with no
    # external definition file, is a Workflow Run Crate.
    sel = select_profile(_model(commands=[_cmd("c1"), _cmd("c2")]), "auto")
    assert sel.profile == "workflow"


def test_auto_phases_promote_to_workflow() -> None:
    sel = select_profile(_model(commands=[_cmd("c1")], phases={"analysis": {}}), "auto")
    assert sel.profile == "workflow"


def test_auto_executed_step_promotes_to_provenance_without_external_file() -> None:
    sel = select_profile(_model(commands=[_cmd("c1", step_id="s1")]), "auto")
    assert sel.profile == "provenance"
    assert sel.confidence == "high"


def test_synthesize_workflow_fills_in_agent_workflow() -> None:
    model = _model(selected_profile="provenance")
    synthesize_workflow(model)
    assert model.workflow is not None
    assert model.workflow["synthetic"] is True
    assert model.workflow["path"].startswith("#workflow/")


def test_synthesize_workflow_noop_for_process() -> None:
    model = _model(selected_profile="process")
    synthesize_workflow(model)
    assert model.workflow is None


def test_synthesize_workflow_preserves_external_definition() -> None:
    model = _model(selected_profile="workflow", workflow={"path": "Snakefile"})
    synthesize_workflow(model)
    assert model.workflow == {"path": "Snakefile"}


def test_profile_selection_is_dataclass() -> None:
    sel = ProfileSelection("process", "https://w3id.org/ro/wfrun/process/0.5", "high", [])
    assert sel.profile == "process"
    assert sel.profile_uri == "https://w3id.org/ro/wfrun/process/0.5"
    assert sel.confidence == "high"
    assert sel.evidence == []
