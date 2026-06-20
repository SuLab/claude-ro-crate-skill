from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.adapters.imports import import_existing_ro_crate
from ro_crate_run.cli import main
from tests.graph_helpers import assert_no_dangling_refs, reachable_ids


def _types(entity: dict) -> list:
    t = entity.get("@type")
    return t if isinstance(t, list) else [t]


def test_import_extracts_actions_steps_params_files(tmp_path: Path) -> None:
    graph = [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork"},
        {"@id": "./", "@type": "Dataset"},
        {
            "@id": "wf.cwl",
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
            "name": "wf.cwl",
        },
        {
            "@id": "urn:uuid:1",
            "@type": "CreateAction",
            "name": "run",
            "instrument": {"@id": "wf.cwl"},
        },
        {"@id": "#step/normalize", "@type": "HowToStep", "name": "normalize"},
        {"@id": "#param/threshold", "@type": "FormalParameter", "name": "threshold"},
        {"@id": "results/out.csv", "@type": "File", "name": "out.csv"},
    ]
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps({"@graph": graph}))
    events = import_existing_ro_crate(tmp_path)
    types = {e["event_type"] for e in events}
    assert "workflow.identified" in types
    assert "execution.command.completed" in types
    assert "workflow.step.identified" in types
    assert "workflow.parameter.declared" in types
    assert "file.observed" in types


def test_imported_workflow_and_files_materialize(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The reducer must PROJECT the imported workflow.identified + file.observed events,
    # not silently drop them (the gap: they reached the journal but no reducer branch).
    src = tmp_path / "src-crate"
    src.mkdir()
    (src / "ro-crate-metadata.json").write_text(json.dumps({"@graph": [
        {"@id": "./", "@type": "Dataset"},
        {"@id": "main.nf", "@type": ["File", "ComputationalWorkflow"], "name": "main.nf"},
        {"@id": "data.csv", "@type": "File", "name": "data.csv"},
    ]}))
    # Realistic import: the referenced files are available locally in the project.
    (tmp_path / "main.nf").write_text("workflow {}\n")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Imp", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["import-ro-crate", str(src)]) == 0
    assert main(["checkpoint"]) == 0

    graph = json.loads(
        (tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json").read_text()
    )["@graph"]
    assert_no_dangling_refs(graph)
    assert any("ComputationalWorkflow" in _types(e) for e in graph), \
        "imported workflow not materialized"
    assert "data.csv" in {e.get("@id") for e in graph}, "imported file not materialized"
    assert "data.csv" in reachable_ids(graph), "imported file is an orphan"


def test_reducer_materializes_terminal_only_command(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A4 (consumer half): an imported Action emits a terminal execution.command.* event.
    # The reducer's terminal branch must setdefault a CommandRecord so a command whose
    # `started` was never seen still materializes, instead of being silently dropped.
    from ro_crate_run.journal import EventWriter
    from ro_crate_run.materialize.run_model import build_run_model

    monkeypatch.chdir(tmp_path)
    assert main(["start", "Terminal only", "--mode", "advisory", "--no-checkpoint"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    EventWriter(state_dir).append(
        "execution.command.completed",
        {
            "command_id": "urn:uuid:imported-1",
            "action_id": "urn:uuid:imported-1",
            "display_command": "imported action",
            "exit_code": 0,
            "imported": True,
        },
    )
    model = build_run_model(state_dir, through_sequence=None)
    records = {c.command_id: c for c in model.commands}
    assert "urn:uuid:imported-1" in records, "terminal-only command was dropped by the reducer"
    record = records["urn:uuid:imported-1"]
    assert record.terminal_status == "completed"
    assert record.action_id == "urn:uuid:imported-1"
    assert record.exit_code == 0


def test_imported_actions_appear_in_rematerialized_graph(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A4 (end to end): an imported crate's Actions must surface as action entities in the
    # re-materialized graph (id == the imported Action's @id), not vanish during projection.
    src = tmp_path / "src-crate"
    src.mkdir()
    (src / "ro-crate-metadata.json").write_text(json.dumps({"@graph": [
        {"@id": "./", "@type": "Dataset"},
        {"@id": "wf.cwl", "@type": ["File", "ComputationalWorkflow"], "name": "wf.cwl"},
        {"@id": "urn:uuid:act-ok", "@type": "CreateAction", "name": "ok",
         "instrument": {"@id": "wf.cwl"}},
        {"@id": "urn:uuid:act-fail", "@type": "CreateAction", "name": "fail",
         "actionStatus": {"@id": "http://schema.org/FailedActionStatus"},
         "instrument": {"@id": "wf.cwl"}},
    ]}))
    (tmp_path / "wf.cwl").write_text("cwlVersion: v1.2\n")
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Imp acts", "--mode", "advisory", "--profile", "auto",
                 "--no-checkpoint"]) == 0
    assert main(["import-ro-crate", str(src)]) == 0
    assert main(["checkpoint"]) == 0

    graph = json.loads(
        (tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json").read_text()
    )["@graph"]
    assert_no_dangling_refs(graph)
    ids = {e.get("@id") for e in graph}
    assert "urn:uuid:act-ok" in ids, "imported (completed) Action not materialized"
    assert "urn:uuid:act-fail" in ids, "imported (failed) Action not materialized"


def test_import_invalid_crate_raises_clean_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no RO-Crate metadata"):
        import_existing_ro_crate(tmp_path / "does-not-exist")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "ro-crate-metadata.json").write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        import_existing_ro_crate(bad)
    nograph = tmp_path / "nograph"
    nograph.mkdir()
    (nograph / "ro-crate-metadata.json").write_text(json.dumps({"hello": "world"}))
    with pytest.raises(ValueError, match="missing @graph"):
        import_existing_ro_crate(nograph)
