from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main


def test_start_status_note_input_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["start", "Demo analysis", "--mode", "monitored", "--no-checkpoint"]) == 0
    assert main(["note", "Excluded rows missing labels.", "--public"]) == 0
    assert main(["decision", "Use normalized counts", "--rationale", "Matches protocol"]) == 0
    data = tmp_path / "data.csv"
    data.write_text("x,y\n1,2\n")
    report = tmp_path / "results" / "report.md"
    report.parent.mkdir()
    assert main(["input", str(data), "--role", "primary-dataset", "--required"]) == 0
    assert main(["output", str(report), "--role", "report", "--required"]) == 0
    assert main(["status", "--json"]) == 0

    events = [
        json.loads(line)
        for line in (tmp_path / ".ro-crate-run/events.ndjson").read_text().splitlines()
    ]
    assert [e["event_type"] for e in events][:2] == ["run.started", "environment.observed"]
    assert "human.note" in [e["event_type"] for e in events]
    assert "human.decision" in [e["event_type"] for e in events]
    assert "workflow.input.declared" in [e["event_type"] for e in events]
    assert "workflow.output.declared" in [e["event_type"] for e in events]


def _strip_timestamps(graph: list[dict]) -> list[dict]:
    """Remove timestamp fields that legitimately change between checkpoints."""
    timestamp_keys = {"datePublished", "dateModified"}
    return [{k: v for k, v in e.items() if k not in timestamp_keys} for e in graph]


def test_checkpoint_rebuild_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Determinism", "--no-checkpoint"]) == 0
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
    first = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())
    assert main(["checkpoint"]) == 0
    second = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())
    # datePublished reflects checkpoint time so differs between runs; dateModified
    # reflects the latest event timestamp and also changes as checkpoint events are added.
    # All other graph structure must be identical.
    assert _strip_timestamps(first["@graph"]) == _strip_timestamps(second["@graph"])


def test_start_persists_session_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-abc")
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    state = json.loads((tmp_path / ".ro-crate-run" / "state.json").read_text())
    assert state["session_id"] == "sess-abc"


def test_declare_output_populates_known_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "out.txt").write_text("hello\n")
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["output", "out.txt", "--required"]) == 0
    state = json.loads((tmp_path / ".ro-crate-run" / "state.json").read_text())
    assert any(o["path"] == "out.txt" and o["sha256"] for o in state["known_outputs"])


def test_status_recovers_abandoned_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    from ro_crate_run.journal import EventWriter

    EventWriter(tmp_path / ".ro-crate-run").append(
        "execution.command.started", {"command_id": "cmd_x"}, source_kind="human_cli"
    )
    assert main(["status"]) == 0  # triggers ensure_recovered
    from ro_crate_run.state import read_events

    types = [e["event_type"] for e in read_events(tmp_path / ".ro-crate-run")]
    assert "execution.command.blocked" in types
