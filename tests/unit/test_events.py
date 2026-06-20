from __future__ import annotations

import math
from pathlib import Path

import pytest

from ro_crate_run import commands
from ro_crate_run.events import actor_for_source, canonical_json, compute_event_hash, new_event
from ro_crate_run.state import read_events


def _types(tmp_path: Path) -> list[str]:
    return [e["event_type"] for e in read_events(tmp_path / ".ro-crate-run")]


def test_note_with_secret_emits_redaction_applied(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)
    commands.note("set API_KEY=abcd1234supersecretvalue", public=False)
    types = _types(tmp_path)
    assert "human.note" in types
    assert "redaction.applied" in types


def test_canonical_json_is_stable() -> None:
    assert canonical_json({"b": 1, "a": "x"}) == '{"a":"x","b":1}'


def test_event_hash_ignores_event_hash_field() -> None:
    event = {"event_id": "evt_1", "previous_event_hash": "sha256:abc", "payload": {"x": 1}}
    h1 = compute_event_hash(event)
    event["event_hash"] = "sha256:wrong"
    assert compute_event_hash(event) == h1


def test_new_event_rejects_null_payload_values() -> None:
    with pytest.raises(ValueError, match="JSON null"):
        new_event(event_type="human.note", payload={"text": None})


def test_actor_for_source_human_cli_is_person() -> None:
    actor = actor_for_source("human_cli")
    assert (actor.type, actor.id, actor.name) == ("Person", "actor:human", "Human operator")


def test_actor_for_source_claude_hook_is_claude_code() -> None:
    actor = actor_for_source("claude_hook")
    assert (actor.type, actor.id) == ("SoftwareApplication", "actor:claude-code")


def test_actor_for_source_default_is_rcr() -> None:
    actor = actor_for_source("materializer")
    assert (actor.type, actor.id) == ("SoftwareApplication", "actor:rcr")


def test_new_event_source_version_tracks_package(monkeypatch) -> None:
    import ro_crate_run.events as events_mod

    monkeypatch.setattr(events_mod, "__version__", "9.9.9", raising=False)
    event = events_mod.new_event("human.note", {"text": "x"})
    assert event.source.version == "9.9.9"


def test_new_event_schema_version_is_1_1_0() -> None:
    event = new_event("human.note", {"text": "x"})
    assert event.schema_version == "1.1.0"


def test_canonical_json_sorts_nested_keys_and_unicode() -> None:
    assert canonical_json({"z": {"b": 2, "a": 1}, "name": "café"}) == '{"name":"café","z":{"a":1,"b":2}}'


def test_canonical_json_numbers_are_stable() -> None:
    assert canonical_json({"i": 10, "f": 0.5}) == '{"f":0.5,"i":10}'


def test_canonical_json_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": math.inf})


def test_canonical_json_documents_scheme() -> None:
    import ro_crate_run.events as events_mod

    assert events_mod.canonical_json.__doc__ is not None
    assert "deterministic" in events_mod.canonical_json.__doc__.lower()
