"""Validation level 0 (journal integrity): hash-chain linkage, monotonic
sequence, required fields, ISO-8601 timestamps, the registered event-type
vocabulary, and command start/terminal pairing for the append-only journal."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from typing import Any

from ro_crate_run.constants import COMMAND_TERMINAL_EVENTS, EVENT_TYPES, LEVEL_JOURNAL
from ro_crate_run.events import compute_event_hash
from ro_crate_run.models import ValidationFinding

from ._findings import level_finding
from .context import ValidationContext

_REQUIRED_FIELDS = (
    "event_id", "event_type", "schema_version", "run_id", "sequence", "timestamp",
    "actor", "source", "visibility", "observed", "declared", "inferred", "redacted",
    "previous_event_hash", "event_hash", "payload",
)

# L0 (journal) findings are always errors; the level is bound once here.
_finding = partial(level_finding, LEVEL_JOURNAL)


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return True
    except ValueError:
        return False


def check_journal(ctx: ValidationContext) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if ctx.journal_parse_error is not None:
        findings.append(_finding("malformed_ndjson", f"Invalid NDJSON: {ctx.journal_parse_error}"))
        return findings

    previous: str | None = None
    seen: set[str] = set()
    started: dict[str, dict[str, Any]] = {}
    terminated: set[str] = set()
    for idx, event in enumerate(ctx.events, start=1):
        # Locate every in-loop finding at the offending event so a single break in a
        # long journal is traceable: prefer its event_id, falling back to the 1-based
        # position when the id itself is the missing/invalid field.
        at = str(event.get("event_id") or f"sequence:{idx}")
        for key in _REQUIRED_FIELDS:
            if key not in event:
                findings.append(_finding("missing_event_field", f"Event missing {key}", at))
        if event.get("sequence") != idx:
            findings.append(_finding("sequence_gap", "Event sequence is not monotonic", at))
        if event.get("event_id") in seen:
            findings.append(_finding("duplicate_event_id", "Duplicate event id", at))
        seen.add(str(event.get("event_id")))
        if not _valid_timestamp(event.get("timestamp")):
            findings.append(_finding("invalid_timestamp", "Event timestamp is not valid ISO-8601 UTC", at))
        if not isinstance(event.get("redacted"), bool):
            findings.append(_finding("invalid_redaction_marker", "Event 'redacted' marker is not boolean", at))
        if event.get("event_type") not in EVENT_TYPES:
            findings.append(_finding(
                "unknown_event_type",
                f"Event type {event.get('event_type')!r} is not in the registered vocabulary",
                at,
            ))
        if event.get("previous_event_hash") != previous:
            findings.append(_finding("hash_chain_mismatch", "Previous hash mismatch", at))
        if event.get("event_hash") != compute_event_hash(event):
            findings.append(_finding("event_hash_mismatch", "Event hash mismatch", at))
        previous = event.get("event_hash")
        payload = event.get("payload", {})
        if event.get("event_type") == "execution.command.started" and isinstance(payload, dict):
            started[str(payload.get("command_id"))] = event
        if event.get("event_type") in COMMAND_TERMINAL_EVENTS and isinstance(payload, dict):
            terminated.add(str(payload.get("command_id")))

    if not ctx.active_run:
        for command_id in sorted(started):
            if command_id not in terminated:
                findings.append(
                    _finding("unterminated_command", f"Command {command_id} has no terminal event")
                )
    return findings
