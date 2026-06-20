from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

from .events import actor_for_source, compute_event_hash, event_to_dict, new_event
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
        # `hold_lock=False` is for callers (recovery) that already hold the append
        # FileLock for the whole read-modify-write — re-acquiring it on a second fd
        # would deadlock.
        lock = FileLock(str(self.lock_path)) if hold_lock else contextlib.nullcontext()
        with lock:
            state = load_state(self.state_dir)
            payload, policy_redacted = self._redact_payload(payload)
            sequence = state.sequence + 1
            # Resolve actor: explicit override > event-type special case > source-derived
            resolved_actor = actor or actor_for_source(source_kind, source_name)
            if event_type == "human.prompt":
                # The prompt is authored by the human user, so the actor is a Person.
                resolved_actor = Actor(type="Person", id="actor:human", name="Human operator")
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
            journal = self.state_dir / "events.ndjson"
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(
                    __import__("json").dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            # Remote mirror after fsync. Best-effort by default (never blocks the
            # local journal, which is authoritative); when remote_journal.fail_closed is
            # set, a mirror failure is raised to the caller instead of silently swallowed
            # (the local event is already committed, but the operator is alerted).
            from .remote_journal import mirror_event
            from .state import load_config

            _rj = load_config(self.state_dir).remote_journal
            try:
                _mirror_ok = mirror_event(
                    _rj,
                    __import__("json").dumps(data, sort_keys=True, separators=(",", ":")),
                )
            except Exception:  # pragma: no cover - network/transport failure
                _mirror_ok = False
            if not _mirror_ok and getattr(_rj, "fail_closed", False) and getattr(_rj, "enabled", False):
                raise RuntimeError(
                    "remote journal mirror failed and remote_journal.fail_closed is set"
                )
            state.sequence = sequence
            state.last_event_hash = event.event_hash
            state.updated_at = utc_now()
            if event_type == "crate.checkpoint.completed":
                state.dirty = False
            elif event_type in {"crate.validation.started", "crate.validation.completed"}:
                # Validation observes the current projection, but it does not materialize
                # events into the crate. Preserve the prior dirty state so standalone
                # `rcr validate` cannot make a stale crate look fresh.
                pass
            elif event_type in {"crate.checkpoint.failed", "crate.validation.failed"}:
                state.dirty = True
            elif not event_type.startswith("crate.checkpoint"):
                # crate.checkpoint.started does not change dirty; dirty is only
                # cleared once the checkpoint successfully completes.
                state.dirty = True
            write_state(self.state_dir, state)
            return event

    def _redact_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            from .redaction import Redactor

            redacted, applied = Redactor.from_config(
                load_config(self.state_dir), state_dir=self.state_dir
            ).redact_value(payload)
        except Exception:
            # FAIL CLOSED: a broken redaction policy (e.g. an invalid custom regex) must NOT
            # cause the original, potentially-secret-bearing payload to be persisted to the
            # immutable journal. Drop the content, keep only the (non-sensitive) key names,
            # and mark the event redacted.
            return {"redaction_error": True, "keys": sorted(map(str, payload.keys()))}, True
        return cast(dict[str, Any], redacted), applied > 0
