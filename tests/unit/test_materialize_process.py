from __future__ import annotations

import json
import time as _time
from pathlib import Path

import ro_crate_run.materialize.builder as builder_mod
from ro_crate_run.cli import main
from ro_crate_run.materialize.run_model import build_run_model
from ro_crate_run.models import ValidationReport
from ro_crate_run.state import load_state
from tests.graph_helpers import assert_no_dangling_refs, resolve_ref


def test_run_model_collects_declarations_and_commands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Process model", "--no-checkpoint"]) == 0
    (tmp_path / "input.txt").write_text("input\n")
    assert main(["input", "input.txt", "--role", "primary"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )

    model = build_run_model(tmp_path / ".ro-crate-run", through_sequence=None)

    assert model.title == "Process model"
    assert len(model.inputs) == 1
    assert len(model.commands) == 1
    assert model.commands[0].terminal_status == "completed"
    assert model.commands[0].outputs == ["out.txt"]


def test_aborted_run_surfaces_run_status_on_crate_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Abort demo", "--no-checkpoint"]) == 0

    # A non-aborted run carries no run-status marker on the root.
    assert main(["checkpoint"]) == 0
    metadata_path = tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json"
    root = {e["@id"]: e for e in json.loads(metadata_path.read_text())["@graph"]}["./"]
    assert "additionalProperty" not in root

    # After `rcr abort`, re-checkpointing surfaces an aborted run-status PropertyValue so a
    # consumer can tell the run ended early.
    assert main(["abort", "ran out of time"]) == 0
    assert main(["checkpoint"]) == 0
    graph = json.loads(metadata_path.read_text())["@graph"]
    root = {e["@id"]: e for e in graph}["./"]
    # The inline run-status PropertyValue is node-ified into a top-level #embedded/* entity
    # (RO-Crate 1.2 MUST: no anonymous inlining); the root carries a reference to it.
    resolved = resolve_ref(root["additionalProperty"], graph)
    assert resolved["@type"] == "PropertyValue"
    assert resolved["propertyID"] == "run-status"
    assert resolved["value"] == "aborted"


def test_checkpoint_writes_ro_crate_12_process_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Process crate", "--no-checkpoint"]) == 0
    (tmp_path / "input.txt").write_text("input\n")
    assert main(["input", "input.txt", "--role", "primary-dataset"]) == 0
    assert (
        main(
            [
                "run",
                "--inputs",
                "input.txt",
                "--outputs",
                "result.txt",
                "--",
                "python3",
                "-c",
                "open('result.txt','w').write('result')",
            ]
        )
        == 0
    )

    assert main(["checkpoint"]) == 0

    metadata_path = tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json"
    graph = json.loads(metadata_path.read_text())
    entities = {entity["@id"]: entity for entity in graph["@graph"]}
    descriptor = entities["ro-crate-metadata.json"]
    root = entities["./"]

    assert graph["@context"][0] == "https://w3id.org/ro/crate/1.2/context"
    assert descriptor["conformsTo"]["@id"] == "https://w3id.org/ro/crate/1.2"
    assert descriptor["about"]["@id"] == "./"
    assert root["@type"] == "Dataset"
    assert root["name"] == "Process crate"
    assert root["datePublished"].endswith("Z")
    assert root["license"]["@id"] == "https://creativecommons.org/licenses/by/4.0/"
    assert {"@id": "https://w3id.org/ro/wfrun/process/0.5"} in root["conformsTo"]
    assert all(value is not None for entity in graph["@graph"] for value in entity.values())
    action_entities = [e for e in graph["@graph"] if e.get("@type") == "CreateAction"]
    assert len(action_entities) == 1
    action = action_entities[0]
    assert action["actionStatus"]["@id"] == "http://schema.org/CompletedActionStatus"
    assert action["object"] == [{"@id": "input.txt"}]
    assert action["result"] == [{"@id": "result.txt"}]


def test_run_model_handles_identified_step_and_results(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Step model", "--no-checkpoint"]) == 0
    from ro_crate_run.journal import EventWriter

    writer = EventWriter(tmp_path / ".ro-crate-run")
    writer.append(
        "workflow.step.identified", {"step_id": "step-1", "name": "step-1"}, source_kind="materializer"
    )
    writer.append(
        "human.accepted_result", {"label": "final output"}, source_kind="human_cli"
    )
    writer.append(
        "human.rejected_result", {"label": "draft"}, source_kind="human_cli"
    )
    writer.append("run.aborted", {}, source_kind="skill_command")

    model = build_run_model(tmp_path / ".ro-crate-run", through_sequence=None)

    assert model.aborted is True
    assert any(r.get("accepted") is True for r in model.results)
    assert any(r.get("accepted") is False for r in model.results)
    assert "step-1" in model.steps


# ---------------------------------------------------------------------------
# Task 7: dateModified reflects the latest event
# ---------------------------------------------------------------------------


def test_date_modified_advances_past_date_created(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Modified", "--no-checkpoint"]) == 0
    _time.sleep(0.01)
    assert main(["note", "later activity"]) == 0
    assert main(["checkpoint"]) == 0
    graph = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())
    root = next(e for e in graph["@graph"] if e["@id"] == "./")
    assert root["dateModified"] >= root["dateCreated"]
    assert root["dateModified"] != root["dateCreated"]


# ---------------------------------------------------------------------------
# Task 8: datePublished is the checkpoint time
# ---------------------------------------------------------------------------


def test_date_published_is_checkpoint_time_not_creation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Published", "--no-checkpoint"]) == 0
    _time.sleep(0.01)
    assert main(["checkpoint"]) == 0
    graph = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())
    root = next(e for e in graph["@graph"] if e["@id"] == "./")
    assert root["datePublished"].endswith("Z")
    assert root["datePublished"] >= root["dateCreated"]
    assert root["datePublished"] != root["dateCreated"]


# ---------------------------------------------------------------------------
# Task 10: Do not clear dirty on a failed checkpoint validation
# ---------------------------------------------------------------------------


def test_process_crate_has_actors_and_no_dangling_refs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--profile", "process", "--no-checkpoint"]) == 0
    (tmp_path / "out.txt").write_text("ok\n")
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )
    assert main(["checkpoint"]) == 0
    meta = json.loads(
        (tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json").read_text()
    )
    graph = meta["@graph"]
    ids = {e["@id"] for e in graph}
    assert "#actor/human" in ids and "#actor/rcr" in ids and "#actor/python" in ids
    # The command action's instrument now resolves to an emitted software entity.
    def _type_set(e: dict) -> set:
        t = e.get("@type")
        return set(t) if isinstance(t, list) else {t}

    actions = [
        e
        for e in graph
        if _type_set(e) & {"CreateAction", "Action", "UpdateAction", "DeleteAction"}
    ]
    assert actions and actions[0]["instrument"]["@id"] in ids
    assert_no_dangling_refs(graph)


def test_failed_validation_keeps_run_dirty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Dirty", "--no-checkpoint"]) == 0
    state_dir = tmp_path / ".ro-crate-run"

    def _failed(*args: object, **kwargs: object) -> ValidationReport:
        return ValidationReport(
            status="failed",
            profile="process",
            profile_uri="https://w3id.org/ro/wfrun/process/0.5",
            levels={"ro_crate": "failed"},
            errors=[],
            warnings=[],
        )

    monkeypatch.setattr(builder_mod, "validate_run", _failed)
    assert builder_mod.checkpoint(state_dir, "auto") == 1
    assert load_state(state_dir).dirty is True
