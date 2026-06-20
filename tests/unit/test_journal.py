from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.config import default_config
from ro_crate_run.constants import dirty_effect
from ro_crate_run.journal import EventWriter
from ro_crate_run.state import (
    ensure_runtime_dirs,
    initial_state,
    load_state,
    write_config,
    write_state,
)


def _bootstrap(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_dirs(state_dir)
    cfg = default_config()
    state = initial_state("Demo", cfg)
    state.session_id = "sess-123"
    write_config(state_dir, cfg)
    write_state(state_dir, state)


def test_event_writer_appends_sequence_and_hash(tmp_path: Path) -> None:
    cfg = default_config(project_name="demo")
    state = initial_state("Demo run", cfg, now="2026-06-17T20:00:00Z")
    state_dir = tmp_path / ".ro-crate-run"
    state_dir.mkdir()
    write_config(state_dir, cfg)
    write_state(state_dir, state)

    writer = EventWriter(state_dir)
    event = writer.append("human.note", payload={"text": "hello"}, source_kind="human_cli")

    lines = (state_dir / "events.ndjson").read_text().splitlines()
    saved = json.loads(lines[0])
    assert event.sequence == 1
    assert saved["sequence"] == 1
    assert saved["event_hash"].startswith("sha256:")
    assert saved["previous_event_hash"] is None


def test_append_sets_person_actor_for_human_cli(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    event = EventWriter(state_dir).append("human.note", {"text": "x"}, source_kind="human_cli")
    assert event.actor.type == "Person"
    assert event.actor.id == "actor:human"


def test_append_inherits_session_id_from_state(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    event = EventWriter(state_dir).append("human.note", {"text": "x"}, source_kind="human_cli")
    assert event.session_id == "sess-123"


def test_append_human_prompt_actor_is_person(tmp_path: Path) -> None:
    # The human authored the prompt, so the actor is a Person (SPEC §11.4).
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    event = EventWriter(state_dir).append(
        "human.prompt", {"prompt": "hi"}, source_kind="claude_hook"
    )
    assert event.actor.type == "Person"
    assert event.actor.id == "actor:human"


def test_validation_events_preserve_or_mark_dirty_without_checkpointing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    writer = EventWriter(state_dir)
    writer.append("crate.checkpoint.completed", {"status": "passed"}, source_kind="materializer")
    assert load_state(state_dir).dirty is False
    writer.append("crate.validation.completed", {"status": "passed"}, source_kind="validator")
    assert load_state(state_dir).dirty is False
    writer.append("human.note", {"text": "stale"}, source_kind="human_cli")
    assert load_state(state_dir).dirty is True
    writer.append("crate.validation.completed", {"status": "passed"}, source_kind="validator")
    assert load_state(state_dir).dirty is True
    writer.append("crate.validation.failed", {"status": "failed"}, source_kind="validator")
    assert load_state(state_dir).dirty is True


def test_append_dirty_matches_dirty_effect(tmp_path: Path) -> None:
    # The writer's dirty bookkeeping is driven entirely by constants.dirty_effect.
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    writer = EventWriter(state_dir)

    # A materializing event ("set") makes the crate stale.
    assert dirty_effect("human.note") == "set"
    writer.append("human.note", {"text": "x"}, source_kind="human_cli")
    assert load_state(state_dir).dirty is True

    # checkpoint.completed ("clear") materializes the pending events.
    assert dirty_effect("crate.checkpoint.completed") == "clear"
    writer.append("crate.checkpoint.completed", {"status": "passed"}, source_kind="materializer")
    assert load_state(state_dir).dirty is False

    # A "preserve" bookkeeping event leaves the freshly-clean state untouched.
    assert dirty_effect("crate.checkpoint.started") == "preserve"
    writer.append("crate.checkpoint.started", {}, source_kind="materializer")
    assert load_state(state_dir).dirty is False


def test_strict_events_raises_on_unregistered_type(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # With RCR_STRICT_EVENTS set, emitting a type outside the registered vocabulary
    # fails loudly so authoring drift is caught in tests.
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    monkeypatch.setenv("RCR_STRICT_EVENTS", "1")
    with pytest.raises(ValueError, match="registered vocabulary"):
        EventWriter(state_dir).append("not.a.real.event", {}, source_kind="materializer")


def test_strict_events_unset_does_not_block_unknown_type(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Production (flag unset) must still degrade gracefully and persist the event.
    state_dir = tmp_path / ".ro-crate-run"
    _bootstrap(state_dir)
    monkeypatch.delenv("RCR_STRICT_EVENTS", raising=False)
    event = EventWriter(state_dir).append("not.a.real.event", {}, source_kind="materializer")
    assert event.event_type == "not.a.real.event"
