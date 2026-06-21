"""Event construction, the canonical JSON encoder, and the shared actor roster.

This module owns the single deterministic JSON encoding used both for the
event hash chain and for on-disk journal lines (``canonical_json`` /
``dump_event_line``), the ``new_event`` factory, and the one source of truth
for actor identities. The roster (``ACTOR_NAMES`` / ``ACTOR_TYPES``) is keyed
by role; helpers derive the two parallel id namespaces from it -- event-level
``actor:<role>`` ids that ride on journal events, and crate-level
``#actor/<role>`` ids emitted into the RO-Crate graph -- so the display names
and ``@type`` values are maintained in exactly one place.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from typing import Any

from . import __version__
from .clock import utc_now
from .constants import EVENT_SCHEMA_VERSION
from .models import Actor, EventSource, RcrEvent

# Display names and @type for each actor role. Single source of truth for both
# the event-level (actor:<role>) and crate-level (#actor/<role>) id namespaces.
ACTOR_NAMES: dict[str, str] = {
    "human": "Human operator",
    "rcr": "RO-Crate Run",
    "claude-code": "Claude Code",
    "ci": "CI",
}
ACTOR_TYPES: dict[str, str] = {
    "human": "Person",
    "rcr": "SoftwareApplication",
    "claude-code": "SoftwareApplication",
    "ci": "System",
}

# Map an event source_kind to the actor role it acts as. Unknown sources fall
# back to the rcr (tooling) role.
_ROLE_BY_SOURCE: dict[str, str] = {
    "human_cli": "human",
    "claude_hook": "claude-code",
    "skill_command": "rcr",
    "materializer": "rcr",
    "validator": "rcr",
    "ci": "ci",
}
_DEFAULT_ROLE = "rcr"


def event_actor_id(role: str) -> str:
    """Event-level actor id (colon namespace) carried on journal events."""
    return f"actor:{role}"


def crate_actor_id(role: str) -> str:
    """Crate-level actor id (slash namespace) emitted into the RO-Crate graph."""
    return f"#actor/{role}"


def engine_actor_id(engine: str) -> str:
    """Crate-level actor id for a workflow engine SoftwareApplication."""
    return f"#actor/engine/{engine}"


def actor_for_source(source_kind: str) -> Actor:
    """Return the event-level Actor for a source_kind, derived from the roster.

    Unknown source kinds fall back to the rcr (tooling) role.
    """
    role = _ROLE_BY_SOURCE.get(source_kind, _DEFAULT_ROLE)
    return Actor(type=ACTOR_TYPES[role], id=event_actor_id(role), name=ACTOR_NAMES[role])


def verify_hash_chain(raw_events: list[dict[str, Any]]) -> str | None:
    """Walk the event hash chain; return the first broken-link message, else None.

    Each event's ``previous_event_hash`` must equal the prior event's
    ``event_hash`` (``None`` before the first), and its ``event_hash`` must equal
    ``compute_event_hash`` of the event. Returns the message for the first broken
    link (previous-hash mismatch checked before event-hash mismatch), or ``None``
    when the chain is intact or empty.
    """
    previous: str | None = None
    for item in raw_events:
        if item.get("previous_event_hash") != previous:
            return "hash chain previous hash mismatch"
        if item.get("event_hash") != compute_event_hash(item):
            return "hash chain event hash mismatch"
        previous = item.get("event_hash")
    return None


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for hashing and on-disk event lines.

    Scheme (a defined, tested equivalent to RFC 8785 per SPEC §11.5):
    UTF-8 output (ensure_ascii=False), object keys sorted, no insignificant
    whitespace (compact separators), and non-finite numbers rejected
    (allow_nan=False). The writer and validator both hash via this function,
    so they always agree.
    """
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def dump_event_line(data: dict[str, Any]) -> str:
    """Encode one event as its canonical newline-terminated on-disk journal line.

    The single canonical NDJSON encoder: it is exactly ``canonical_json`` (the
    same form that is hashed) plus a trailing newline, so the stored line and
    the hashed bytes never diverge.
    """
    return canonical_json(data) + "\n"


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
    actor = actor or actor_for_source(source_kind)
    return RcrEvent(
        event_id=f"evt_{uuid.uuid4().hex}",
        event_type=event_type,
        schema_version=EVENT_SCHEMA_VERSION,
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
    """Flatten an RcrEvent (and its nested Actor/EventSource) to the plain dict
    used for hashing and on-disk journal lines."""
    return asdict(event)


def event_from_dict(data: dict[str, Any]) -> RcrEvent:
    """Reconstruct an RcrEvent from its journal dict form.

    Rebuilds the nested Actor/EventSource dataclasses, coerces sequence/bool
    fields, and tolerates absent optional fields (session_id, phase_id, step_id,
    previous_event_hash, event_hash, payload).
    """
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
    """Recursively raise ValueError if any JSON null appears in an event payload.

    Absent fields must be omitted, not encoded as null. This is the deliberate
    opposite of ``models.strip_none`` (which drops None during crate assembly);
    the two policies are intentionally not unified.
    """
    if value is None:
        raise ValueError("JSON null is not allowed in event payloads")
    if isinstance(value, dict):
        for item in value.values():
            _reject_null(item)
    elif isinstance(value, list):
        for item in value:
            _reject_null(item)
