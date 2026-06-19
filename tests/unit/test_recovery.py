from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.config import default_config
from ro_crate_run.journal import EventWriter
from ro_crate_run.recovery import recover_state
from ro_crate_run.state import (
    ensure_runtime_dirs,
    initial_state,
    load_state,
    read_events,
    run_is_active,
    write_config,
    write_state,
)


def make_run(state_dir: Path) -> None:
    state_dir.mkdir()
    cfg = default_config(project_name="demo")
    write_config(state_dir, cfg)
    write_state(state_dir, initial_state("Demo", cfg, now="2026-06-17T20:00:00Z"))


def _bootstrap(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_dirs(state_dir)
    cfg = default_config()
    write_config(state_dir, cfg)
    write_state(state_dir, initial_state("Demo", cfg))


def test_recovery_rebuilds_state_sequence_when_state_lags(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    make_run(state_dir)
    writer = EventWriter(state_dir)
    writer.append("human.note", payload={"text": "one"}, source_kind="human_cli")
    stale = load_state(state_dir)
    stale.sequence = 0
    stale.last_event_hash = None
    write_state(state_dir, stale)

    result = recover_state(state_dir)

    assert result.repaired is True
    assert load_state(state_dir).sequence == 2
    assert result.events[-1].event_type == "journal.repair.completed"


def test_recovery_marks_started_command_abandoned(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    make_run(state_dir)
    writer = EventWriter(state_dir)
    started = writer.append(
        "execution.command.started",
        payload={"command_id": "cmd_1", "argv": ["python3", "-c", "print(1)"]},
        source_kind="human_cli",
    )

    result = recover_state(state_dir, active_run=False)

    assert result.repaired is True
    event_types = [e.event_type for e in result.events]
    assert "execution.command.blocked" in event_types
    blocked = [e for e in result.events if e.event_type == "execution.command.blocked"][-1]
    assert blocked.payload["failure_class"] == "abandoned"
    assert blocked.payload["started_event_id"] == started.event_id


def test_recovery_repairs_partial_trailing_journal_line(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    make_run(state_dir)
    writer = EventWriter(state_dir)
    writer.append("human.note", payload={"text": "one"}, source_kind="human_cli")
    with (state_dir / "events.ndjson").open("a", encoding="utf-8") as handle:
        handle.write('{"event_id": "partial"')

    result = recover_state(state_dir)

    assert result.repaired is True
    assert all(event.event_id != "partial" for event in result.events)
    assert '"event_id": "partial"' not in (state_dir / "events.ndjson").read_text()


def test_abandoned_command_marked_blocked(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    EventWriter(state_dir).append(
        "execution.command.started", {"command_id": "cmd_1"}, source_kind="human_cli"
    )
    recover_state(state_dir, active_run=False)
    types = [e["event_type"] for e in read_events(state_dir)]
    assert "execution.command.blocked" in types
    assert "execution.command.failed" not in types


def test_fatal_hash_mismatch_emits_repair_failed(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    EventWriter(state_dir).append("human.note", {"text": "x"}, source_kind="human_cli")
    journal = state_dir / "events.ndjson"
    lines = journal.read_text().splitlines()
    obj = json.loads(lines[0])
    obj["event_hash"] = "sha256:tampered"
    journal.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    result = recover_state(state_dir, active_run=False)
    assert result.fatal is True
    types = [e["event_type"] for e in read_events(state_dir)]
    assert "journal.repair.failed" in types


def test_run_is_active_false_after_finalize(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    assert run_is_active(state_dir) is True
    EventWriter(state_dir).append("run.finalized", {}, source_kind="skill_command")
    assert run_is_active(state_dir) is False


def test_duplicate_start_does_not_clobber_active_run(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A second `rcr start` on an active run MUST NOT rewrite state.json with a fresh
    # initial_state — that orphans the journal (new run_id, reset sequence) and breaks
    # the hash chain. It must be idempotent: same run_id, single run.started, clean journal.
    from ro_crate_run.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["start", "Dup", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    first_run_id = load_state(state_dir).run_id
    EventWriter(state_dir).append("human.note", {"text": "mid"}, source_kind="human_cli")

    # Duplicate start, same args AND different args — neither may corrupt the run.
    assert main(["start", "Dup", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["start", "Other", "--mode", "enforced", "--profile", "workflow", "--no-checkpoint"]) == 0

    assert load_state(state_dir).run_id == first_run_id, "run_id changed — state was clobbered"
    types = [e["event_type"] for e in read_events(state_dir)]
    assert types.count("run.started") == 1, f"expected one run.started, got {types}"
    # The journal still recovers without a fatal hash/sequence break.
    result = recover_state(state_dir)
    assert result.fatal is False
    assert "journal.repair.failed" not in [e.event_type for e in result.events]
