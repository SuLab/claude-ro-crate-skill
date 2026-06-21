"""Treat the journal as authoritative and rebuild/repair derived state.

Runs at the top of every CLI command and hook startup: it repairs a partial
trailing line, reconciles a lagged ``state.json`` to the journal, and marks
abandoned commands blocked. ``is_active_run`` is the single source for whether a
run is still active.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock

from .constants import COMMAND_TERMINAL_EVENTS, RUN_TERMINAL_EVENTS
from .events import dump_event_line, event_from_dict, verify_hash_chain
from .journal import EventWriter
from .models import RcrEvent
from .state import load_state, write_state


@dataclass
class RecoveryResult:
    repaired: bool = False
    fatal: bool = False
    events: list[RcrEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_active_run(events: list[Any]) -> bool:
    """Return True if no terminal event (run.finalized or run.aborted) exists."""
    return not any(e.get("event_type") in RUN_TERMINAL_EVENTS for e in events)


def recover_state(state_dir: Path, active_run: bool = False) -> RecoveryResult:
    # Serialize the entire read-modify-write of the journal + state under the append
    # FileLock. ensure_recovered() runs at every CLI startup, and real Claude sessions
    # fire many hooks concurrently; without this lock a concurrent recovery's partial-line
    # rewrite or state reconciliation races appends and corrupts the hash chain.
    with FileLock(str(state_dir / "lock")):
        return _recover_state_locked(state_dir, active_run)


def _recover_state_locked(state_dir: Path, active_run: bool = False) -> RecoveryResult:
    result = RecoveryResult()
    raw_events, repaired_partial, repair_errors = _read_events_repairing_partial_line(state_dir)
    if repair_errors:
        result.fatal = True
        result.errors.extend(repair_errors)
        _emit_repair(state_dir, "journal.repair.failed", repair_errors[0])
        return result
    parsed = [event_from_dict(item) for item in raw_events]
    result.events = list(parsed)
    chain_error = verify_hash_chain(raw_events)
    if chain_error is not None:
        result.fatal = True
        result.errors.append(chain_error)
        _emit_repair(state_dir, "journal.repair.failed", chain_error)
        return result

    state = load_state(state_dir)
    if parsed and (
        state.sequence != parsed[-1].sequence or state.last_event_hash != parsed[-1].event_hash
    ):
        _emit_repair(state_dir, "journal.repair.started", "state_lagged_journal")
        state.sequence = parsed[-1].sequence
        state.last_event_hash = parsed[-1].event_hash
        write_state(state_dir, state)
        result.repaired = True
        writer = EventWriter(state_dir)
        completed = writer.append(
            "journal.repair.completed",
            {"reason": "state_lagged_journal"},
            source_kind="materializer",
            hold_lock=False,
        )
        result.events.append(completed)

    if repaired_partial:
        _emit_repair(state_dir, "journal.repair.started", "partial_trailing_line_removed")
        completed = EventWriter(state_dir).append(
            "journal.repair.completed",
            {"reason": "partial_trailing_line_removed"},
            source_kind="materializer",
            hold_lock=False,
        )
        result.repaired = True
        result.events.append(completed)

    terminal_ids = {
        event.payload.get("command_id")
        for event in result.events
        if event.event_type in COMMAND_TERMINAL_EVENTS and event.payload.get("command_id")
    }
    if not active_run:
        writer = EventWriter(state_dir)
        for event in list(result.events):
            if (
                event.event_type == "execution.command.started"
                and event.payload.get("command_id") not in terminal_ids
            ):
                _emit_repair(state_dir, "journal.repair.started", "abandoned_command")
                blocked = writer.append(
                    "execution.command.blocked",
                    {
                        "command_id": event.payload["command_id"],
                        "started_event_id": event.event_id,
                        "failure_class": "abandoned",
                        "exit_code": -1,
                    },
                    source_kind="materializer",
                    step_id=event.step_id,
                    hold_lock=False,
                )
                result.repaired = True
                result.events.append(blocked)
    return result


def ensure_recovered(state_dir: Path) -> None:
    if not (state_dir / "state.json").exists():
        return
    recover_state(state_dir, active_run=False)


def _emit_repair(state_dir: Path, event_type: str, reason: str) -> None:
    # Single best-effort emitter for the started/failed repair markers (the only difference
    # was the event-type literal); the completed markers stay inline because they capture
    # the appended event into result.events rather than swallowing it.
    try:
        EventWriter(state_dir).append(
            event_type,
            {"reason": reason},
            source_kind="materializer",
            hold_lock=False,
        )
    except Exception:  # broad by design: repair helper must not raise
        pass


def _read_events_repairing_partial_line(
    state_dir: Path,
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    path = state_dir / "events.ndjson"
    if not path.exists():
        return [], False, []
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: list[dict[str, Any]] = []
    repaired = False
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if idx == len(lines) - 1:
                # Atomic rewrite (tmp + replace, matching state.write_state) so a crash
                # mid-write can never truncate the authoritative append-only journal; the
                # enclosing append FileLock keeps it exclusive with concurrent appends.
                tmp = path.with_name("events.ndjson.tmp")
                tmp.write_text(
                    "".join(dump_event_line(event) for event in parsed),
                    encoding="utf-8",
                )
                tmp.replace(path)
                repaired = True
                break
            return parsed, False, [f"invalid journal JSON at line {idx + 1}: {exc}"]
    return parsed, repaired, []
