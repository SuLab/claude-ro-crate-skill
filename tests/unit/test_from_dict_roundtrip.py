from __future__ import annotations

from pathlib import Path

from ro_crate_run.config import default_config
from ro_crate_run.models import LastCheckpoint, RemoteJournalConfig, ValidationConfig
from ro_crate_run.state import (
    initial_state,
    load_config,
    load_state,
    read_events_safe,
    write_config,
    write_state,
)


def test_write_config_load_config_roundtrip(tmp_path: Path) -> None:
    cfg = default_config(project_name="demo")
    # Mutate a nested config dataclass so the round-trip must reconstruct it, not leave a dict.
    cfg.validation.strict = True
    cfg.validation.require_clean_git = True
    cfg.remote_journal.enabled = True
    cfg.remote_journal.endpoint = "https://example.test/journal"

    write_config(tmp_path, cfg)
    loaded = load_config(tmp_path)

    assert loaded == cfg
    assert isinstance(loaded.validation, ValidationConfig)
    assert loaded.validation.strict is True
    assert isinstance(loaded.remote_journal, RemoteJournalConfig)
    assert loaded.remote_journal.endpoint == "https://example.test/journal"


def test_write_state_load_state_roundtrip(tmp_path: Path) -> None:
    state = initial_state("Demo", default_config())
    state.last_checkpoint = LastCheckpoint(
        event_id="evt-1",
        timestamp="2026-06-20T00:00:00Z",
        event_sequence=3,
        materialized_through_sequence=3,
        validation_status="passed",
        materializer_version="1.0.0",
    )

    write_state(tmp_path, state)
    loaded = load_state(tmp_path)

    assert loaded == state
    assert isinstance(loaded.last_checkpoint, LastCheckpoint)
    assert loaded.last_checkpoint.event_id == "evt-1"


def test_load_state_last_checkpoint_empty_becomes_none(tmp_path: Path) -> None:
    state = initial_state("Demo", default_config())
    assert state.last_checkpoint is None

    write_state(tmp_path, state)
    # A serialized null/absent checkpoint must round-trip back to None, not an empty object.
    loaded = load_state(tmp_path)
    assert loaded.last_checkpoint is None


def test_read_events_safe_clean_journal(tmp_path: Path) -> None:
    journal = tmp_path / "events.ndjson"
    journal.write_text('{"sequence": 1}\n{"sequence": 2}\n', encoding="utf-8")

    events, err = read_events_safe(tmp_path)

    assert err is None
    assert events == [{"sequence": 1}, {"sequence": 2}]


def test_read_events_safe_missing_journal(tmp_path: Path) -> None:
    events, err = read_events_safe(tmp_path)
    assert events == []
    assert err is None


def test_read_events_safe_corrupted_line(tmp_path: Path) -> None:
    journal = tmp_path / "events.ndjson"
    journal.write_text('{"sequence": 1}\nnot-json\n{"sequence": 3}\n', encoding="utf-8")

    events, err = read_events_safe(tmp_path)

    assert events == [{"sequence": 1}]
    assert err is not None
    assert err.startswith("line 2:")
