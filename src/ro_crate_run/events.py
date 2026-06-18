from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from typing import Any

from . import __version__
from .models import Actor, EventSource, RcrEvent
from .time import utc_now

_ACTOR_BY_SOURCE: dict[str, tuple[str, str, str]] = {
    "human_cli": ("Person", "actor:human", "Human operator"),
    "claude_hook": ("SoftwareApplication", "actor:claude-code", "Claude Code"),
    "skill_command": ("SoftwareApplication", "actor:rcr", "RO-Crate Run"),
    "materializer": ("SoftwareApplication", "actor:rcr", "RO-Crate Run"),
    "validator": ("SoftwareApplication", "actor:rcr", "RO-Crate Run"),
    "ci": ("System", "actor:ci", "CI"),
}


def actor_for_source(source_kind: str, source_name: str) -> Actor:
    """Return the Actor for a given source_kind (source_name is accepted but ignored)."""
    kind, actor_id, name = _ACTOR_BY_SOURCE.get(
        source_kind, ("SoftwareApplication", "actor:rcr", "RO-Crate Run")
    )
    return Actor(type=kind, id=actor_id, name=name)


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for the event hash chain.

    Scheme (a defined, tested equivalent to RFC 8785 per SPEC §11.5):
    UTF-8 output (ensure_ascii=False), object keys sorted, no insignificant
    whitespace (compact separators), and non-finite numbers rejected
    (allow_nan=False). The writer and validator both hash via this function,
    so they always agree.
    """
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def compute_event_hash(event: dict[str, Any]) -> str:
    data = dict(event)
    data.pop("event_hash", None)
    return "sha256:" + hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def new_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    run_id: str = "run_pending",
    sequence: int = 0,
    previous_event_hash: str | None = None,
    source_kind: str = "skill_command",
    source_name: str = "rcr",
    visibility: str = "private",
    phase_id: str | None = None,
    step_id: str | None = None,
    observed: bool = True,
    declared: bool = False,
    inferred: bool = False,
    redacted: bool = False,
    session_id: str | None = None,
    timestamp: str | None = None,
    actor: Actor | None = None,
) -> RcrEvent:
    _reject_null(payload)
    actor = actor or actor_for_source(source_kind, source_name)
    return RcrEvent(
        event_id=f"evt_{uuid.uuid4().hex}",
        event_type=event_type,
        schema_version="1.1.0",
        run_id=run_id,
        session_id=session_id,
        sequence=sequence,
        timestamp=timestamp or utc_now(),
        actor=actor,
        source=EventSource(kind=source_kind, name=source_name, version=__version__),
        visibility=visibility,
        phase_id=phase_id,
        step_id=step_id,
        observed=observed,
        declared=declared,
        inferred=inferred,
        redacted=redacted,
        previous_event_hash=previous_event_hash,
        event_hash=None,
        payload=payload,
    )


def event_to_dict(event: RcrEvent) -> dict[str, Any]:
    return asdict(event)


def event_from_dict(data: dict[str, Any]) -> RcrEvent:
    return RcrEvent(
        event_id=data["event_id"],
        event_type=data["event_type"],
        schema_version=data["schema_version"],
        run_id=data["run_id"],
        session_id=data.get("session_id"),
        sequence=int(data["sequence"]),
        timestamp=data["timestamp"],
        actor=Actor(**data["actor"]),
        source=EventSource(**data["source"]),
        visibility=data["visibility"],
        phase_id=data.get("phase_id"),
        step_id=data.get("step_id"),
        observed=bool(data["observed"]),
        declared=bool(data["declared"]),
        inferred=bool(data["inferred"]),
        redacted=bool(data["redacted"]),
        previous_event_hash=data.get("previous_event_hash"),
        event_hash=data.get("event_hash"),
        payload=data.get("payload", {}),
    )


def _reject_null(value: Any) -> None:
    if value is None:
        raise ValueError("JSON null is not allowed in event payloads")
    if isinstance(value, dict):
        for item in value.values():
            _reject_null(item)
    elif isinstance(value, list):
        for item in value:
            _reject_null(item)
