"""Append-only event journal.

Single-event writes go through :meth:`EventWriter.append`, which takes the file
lock, links the hash chain, bumps ``state.sequence``, fsyncs, and best-effort
mirrors to a remote journal. The only other writer is
:meth:`EventWriter.rewrite_chain`, which the ``rcr redact`` command uses to
re-link and atomically rewrite the whole journal under the same lock.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

from .constants import EVENT_TYPES, dirty_effect
from .events import (
    ACTOR_NAMES,
    ACTOR_TYPES,
    actor_for_source,
    compute_event_hash,
    dump_event_line,
    event_actor_id,
    event_to_dict,
    new_event,
)
from .models import Actor, RcrEvent
from .state import load_config, load_state, write_state
from .time import utc_now


class EventWriter:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.state_dir / "lock"

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        source_kind: str = "skill_command",
        source_name: str = "rcr",
        visibility: str = "private",
        observed: bool = True,
        declared: bool = False,
        inferred: bool = False,
        redacted: bool = False,
        phase_id: str | None = None,
        step_id: str | None = None,
        session_id: str | None = None,
        actor: Actor | None = None,
        hold_lock: bool = True,
    ) -> RcrEvent:
        """Append one event to ``events.ndjson`` — the only sanctioned mutator of it.

        Holds the run :class:`FileLock`, redacts the payload before persistence,
        links the hash chain, fsyncs the line, mirrors it to the remote journal
        best-effort, and bumps the derived ``state.sequence``/``state.dirty``.

        ``hold_lock=False`` is for callers (recovery) that already hold the append
        FileLock for the whole read-modify-write; re-acquiring it on a second fd
        would deadlock.
        """
        # Surface unregistered internal emits loudly under test; production still
        # degrades these to hook.unknown via the L0 validator, so never raise there.
        if os.environ.get("RCR_STRICT_EVENTS") and event_type not in EVENT_TYPES:
            raise ValueError(f"event_type {event_type!r} is not in the registered vocabulary")
        lock = FileLock(str(self.lock_path)) if hold_lock else contextlib.nullcontext()
        with lock:
            state = load_state(self.state_dir)
            payload, policy_redacted = self._redact_payload(payload)
            sequence = state.sequence + 1
            # Resolve actor: explicit override > event-type special case > source-derived
            resolved_actor = actor or actor_for_source(source_kind)
            if event_type == "human.prompt":
                # human.prompt is emitted from a Claude hook, so the source-derived
                # actor would be the agent; the prompt is authored by the human, so
                # cast the actor to the Person role from the shared roster.
                resolved_actor = Actor(
                    type=ACTOR_TYPES["human"],
                    id=event_actor_id("human"),
                    name=ACTOR_NAMES["human"],
                )
            # Resolve session_id: explicit override > state session_id
            resolved_session = session_id if session_id is not None else state.session_id
            event = new_event(
                event_type,
                payload,
                run_id=state.run_id,
                sequence=sequence,
                previous_event_hash=state.last_event_hash,
                source_kind=source_kind,
                source_name=source_name,
                visibility=visibility,
                phase_id=phase_id if phase_id is not None else state.current_phase_id,
                step_id=step_id if step_id is not None else state.current_step_id,
                observed=observed,
                declared=declared,
                inferred=inferred,
                redacted=redacted or policy_redacted,
                session_id=resolved_session,
                actor=resolved_actor,
            )
            data = event_to_dict(event)
            data["event_hash"] = compute_event_hash(data)
            event.event_hash = data["event_hash"]
            line = dump_event_line(data)
            journal = self.state_dir / "events.ndjson"
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            # Remote mirror after fsync. Best-effort by default (never blocks the
            # local journal, which is authoritative); when remote_journal.fail_closed is
            # set, a mirror failure is raised to the caller instead of silently swallowed
            # (the local event is already committed, but the operator is alerted).
            from .remote_journal import mirror_event

            _rj = load_config(self.state_dir).remote_journal
            try:
                _mirror_ok = mirror_event(_rj, line)
            except Exception:  # pragma: no cover - network/transport failure
                _mirror_ok = False
            if not _mirror_ok and _rj.fail_closed and _rj.enabled:
                raise RuntimeError(
                    "remote journal mirror failed and remote_journal.fail_closed is set"
                )
            state.sequence = sequence
            state.last_event_hash = event.event_hash
            state.updated_at = utc_now()
            effect = dirty_effect(event_type)
            if effect == "set":
                state.dirty = True
            elif effect == "clear":
                state.dirty = False
            # "preserve" leaves the prior dirty state untouched so checkpoint/validation
            # bookkeeping cannot make a stale crate look fresh.
            write_state(self.state_dir, state)
            return event

    def rewrite_chain(self, events: list[RcrEvent]) -> None:
        """Re-link and atomically rewrite the entire journal — the sole owner of a
        full-chain rewrite (used by the ``rcr redact`` command to persist edited events).

        The caller supplies events whose ``sequence`` and contents are already final;
        this method re-derives the hash chain (so any edited payload still yields a
        valid chain), persists it crash-safely, refreshes the derived state, and
        re-mirrors the rewritten lines. Held under the append ``FileLock`` so it stays
        exclusive with appends and recovery — the same lock those paths take.

        Empty input is a no-op: there is nothing to rewrite and no state to bump.
        """
        if not events:
            return
        with FileLock(str(self.lock_path)):
            previous: str | None = None
            lines: list[str] = []
            for event in events:
                event.previous_event_hash = previous
                event.event_hash = None
                data = event_to_dict(event)
                data["event_hash"] = compute_event_hash(data)
                event.event_hash = data["event_hash"]
                previous = event.event_hash
                lines.append(dump_event_line(data))
            payload = "".join(lines)
            # Atomic rewrite (tmp + replace) so a crash mid-write cannot truncate or
            # corrupt the authoritative journal.
            journal = self.state_dir / "events.ndjson"
            journal_tmp = journal.with_suffix(".ndjson.tmp")
            journal_tmp.write_text(payload, encoding="utf-8")
            journal_tmp.replace(journal)
            # Re-mirror the rewritten chain, reusing append's post-write fail-closed
            # policy: the local journal is authoritative and already committed, so a
            # mirror failure only raises when remote_journal.fail_closed is set.
            from .remote_journal import mirror_event

            _rj = load_config(self.state_dir).remote_journal
            try:
                # Attempt every line (no short-circuit) so the remote receives the
                # full rewritten chain whenever it is reachable.
                _mirror_ok = all([mirror_event(_rj, line) for line in lines])
            except Exception:  # pragma: no cover - network/transport failure
                _mirror_ok = False
            if not _mirror_ok and _rj.fail_closed and _rj.enabled:
                raise RuntimeError(
                    "remote journal mirror failed and remote_journal.fail_closed is set"
                )
            final = events[-1]
            state = load_state(self.state_dir)
            state.sequence = final.sequence
            state.last_event_hash = final.event_hash
            state.updated_at = utc_now()
            effect = dirty_effect(final.event_type)
            if effect == "set":
                state.dirty = True
            elif effect == "clear":
                state.dirty = False
            # "preserve" leaves the prior dirty state untouched, matching append.
            write_state(self.state_dir, state)

    def _redact_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            from .redaction import Redactor

            redacted, applied = Redactor.for_state_dir(self.state_dir).redact_value(payload)
        except Exception:
            # FAIL CLOSED: a broken redaction policy (e.g. an invalid custom regex) must NOT
            # cause the original, potentially-secret-bearing payload to be persisted to the
            # immutable journal. Drop the content, keep only the (non-sensitive) key names,
            # and mark the event redacted.
            return {"redaction_error": True, "keys": sorted(map(str, payload.keys()))}, True
        return cast(dict[str, Any], redacted), applied > 0
