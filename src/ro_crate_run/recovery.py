from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock

from .events import compute_event_hash, event_from_dict
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
    terminal = {"run.finalized", "run.aborted"}
    return not any(e.get("event_type") in terminal for e in events)


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
        _emit_repair_failed(state_dir, repair_errors[0])
        return result
    parsed = [event_from_dict(item) for item in raw_events]
    result.events = list(parsed)
    previous = None
    for item in raw_events:
        if item.get("previous_event_hash") != previous:
            result.fatal = True
            result.errors.append("hash chain previous hash mismatch")
            _emit_repair_failed(state_dir, "hash chain previous hash mismatch")
            return result
        expected = compute_event_hash(item)
        if item.get("event_hash") != expected:
            result.fatal = True
            result.errors.append("hash chain event hash mismatch")
            _emit_repair_failed(state_dir, "hash chain event hash mismatch")
            return result
        previous = item.get("event_hash")

    state = load_state(state_dir)
    if parsed and (
        state.sequence != parsed[-1].sequence or state.last_event_hash != parsed[-1].event_hash
    ):
        _emit_repair_started(state_dir, "state_lagged_journal")
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
        _emit_repair_started(state_dir, "partial_trailing_line_removed")
        completed = EventWriter(state_dir).append(
            "journal.repair.completed",
            {"reason": "partial_trailing_line_removed"},
            source_kind="materializer",
            hold_lock=False,
        )
        result.repaired = True
        result.events.append(completed)

    terminals = {
        "execution.command.completed",
        "execution.command.failed",
        "execution.command.blocked",
    }
    terminal_ids = {
        event.payload.get("command_id")
        for event in result.events
        if event.event_type in terminals and event.payload.get("command_id")
    }
    if not active_run:
        writer = EventWriter(state_dir)
        for event in list(result.events):
            if (
                event.event_type == "execution.command.started"
                and event.payload.get("command_id") not in terminal_ids
            ):
                _emit_repair_started(state_dir, "abandoned_command")
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


def _emit_repair_started(state_dir: Path, reason: str) -> None:
    try:
        EventWriter(state_dir).append(
            "journal.repair.started",
            {"reason": reason},
            source_kind="materializer",
            hold_lock=False,
        )
    except Exception:  # broad by design: repair helper must not raise
        pass


def _emit_repair_failed(state_dir: Path, reason: str) -> None:
    try:
        EventWriter(state_dir).append(
            "journal.repair.failed",
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
                path.write_text(
                    "".join(
                        json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                        for event in parsed
                    ),
                    encoding="utf-8",
                )
                repaired = True
                break
            return parsed, False, [f"invalid journal JSON at line {idx + 1}: {exc}"]
    return parsed, repaired, []
