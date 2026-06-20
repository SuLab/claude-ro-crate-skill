from __future__ import annotations

import json

import pytest

from ro_crate_run.events import (
    ACTOR_NAMES,
    ACTOR_TYPES,
    actor_for_source,
    canonical_json,
    crate_actor_id,
    dump_event_line,
    engine_actor_id,
    event_actor_id,
)


def test_dump_event_line_is_canonical_json_plus_newline() -> None:
    data = {"b": 1, "a": 2, "nested": {"y": True, "x": [1, 2]}}
    assert dump_event_line(data) == canonical_json(data) + "\n"


def test_dump_event_line_preserves_non_ascii_and_round_trips() -> None:
    payload = {"name": "café — résumé", "emoji": "🧬", "k": "Ωmega"}
    line = dump_event_line(payload)
    # Canonical encoder keeps raw UTF-8 (ensure_ascii=False): no \uXXXX escapes.
    assert "\\u" not in line
    assert line.endswith("\n")
    assert json.loads(line) == payload


def test_dump_event_line_rejects_nan() -> None:
    with pytest.raises(ValueError):
        dump_event_line({"x": float("nan")})


# Pin the exact event-level actor cast, frozen against the historical literal table.
EXPECTED_ACTOR_BY_SOURCE = {
    "human_cli": ("Person", "actor:human", "Human operator"),
    "claude_hook": ("SoftwareApplication", "actor:claude-code", "Claude Code"),
    "skill_command": ("SoftwareApplication", "actor:rcr", "RO-Crate Run"),
    "materializer": ("SoftwareApplication", "actor:rcr", "RO-Crate Run"),
    "validator": ("SoftwareApplication", "actor:rcr", "RO-Crate Run"),
    "ci": ("System", "actor:ci", "CI"),
}


@pytest.mark.parametrize(
    ("source_kind", "expected"), sorted(EXPECTED_ACTOR_BY_SOURCE.items())
)
def test_actor_for_source_matches_frozen_table(
    source_kind: str, expected: tuple[str, str, str]
) -> None:
    kind, actor_id, name = expected
    actor = actor_for_source(source_kind)
    assert actor.type == kind
    assert actor.id == actor_id
    assert actor.name == name


def test_actor_for_source_unknown_falls_back_to_rcr() -> None:
    actor = actor_for_source("totally-unknown-source")
    assert actor.type == "SoftwareApplication"
    assert actor.id == "actor:rcr"
    assert actor.name == "RO-Crate Run"


def test_event_actor_id_uses_colon_namespace() -> None:
    assert event_actor_id("human") == "actor:human"
    assert event_actor_id("claude-code") == "actor:claude-code"


def test_crate_actor_id_uses_slash_namespace() -> None:
    assert crate_actor_id("human") == "#actor/human"
    assert crate_actor_id("rcr") == "#actor/rcr"


def test_engine_actor_id() -> None:
    assert engine_actor_id("cwl") == "#actor/engine/cwl"
    assert engine_actor_id("nextflow") == "#actor/engine/nextflow"


def test_roster_keys_are_aligned() -> None:
    assert set(ACTOR_NAMES) == set(ACTOR_TYPES) == {"human", "rcr", "claude-code", "ci"}
