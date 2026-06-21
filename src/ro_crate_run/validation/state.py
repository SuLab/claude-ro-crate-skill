"""Validation level 1 (state integrity): the derived state.json cache agrees
with the journal — run id, hash-chain head, sequence, open phase/step, dirty
accuracy, and the id-map shape."""

from __future__ import annotations

import json
from functools import partial

from ro_crate_run.constants import LEVEL_STATE, dirty_effect
from ro_crate_run.ids import new_id_map
from ro_crate_run.models import ValidationFinding

from ._findings import level_finding
from .context import ValidationContext

# L1 (state) findings; the level is bound once here. Most are errors; the two
# advisory findings (``open_phase``/``open_step``) pass ``severity="warning"``.
_finding = partial(level_finding, LEVEL_STATE)


def check_state(ctx: ValidationContext) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    state, events = ctx.state, ctx.events

    for event in events:
        if event.get("run_id") != state.run_id:
            findings.append(_finding("run_id_mismatch", "Event run_id does not match state"))
            break

    if events:
        journal_hash = events[-1].get("event_hash")
        if state.last_event_hash != journal_hash:
            findings.append(
                _finding("state_hash_mismatch", "state.last_event_hash does not match journal")
            )
        # state.sequence tracks the last event's sequence field, not the line count,
        # so compare against that (sequences may legitimately start above 1 or gap).
        last_sequence = int(events[-1].get("sequence", 0))
        if state.sequence != last_sequence:
            findings.append(
                _finding("state_sequence_mismatch", "state.sequence does not match journal")
            )

    if state.current_phase_id:
        findings.append(_finding(
            "open_phase", f"Run has open phase {state.current_phase_id}", severity="warning"
        ))
    if state.current_step_id:
        findings.append(_finding(
            "open_step", f"Run has open step {state.current_step_id}", severity="warning"
        ))

    lc = state.last_checkpoint
    if lc is not None:
        if lc.materialized_through_sequence > state.sequence or lc.event_sequence > state.sequence:
            findings.append(
                _finding("checkpoint_sequence_invalid", "last_checkpoint sequence exceeds journal")
            )

    # Dirty-flag accuracy: only meaningful when a prior checkpoint exists.
    if lc is not None:
        through = lc.materialized_through_sequence
        pending = any(
            int(e.get("sequence", 0)) > through
            and dirty_effect(str(e.get("event_type", ""))) == "set"
            for e in events
        )
        if pending and not state.dirty:
            findings.append(
                _finding("dirty_flag_inaccurate", "Uncheckpointed events exist but dirty is false")
            )
        if not pending and state.dirty and lc.validation_status != "failed":
            findings.append(
                _finding("dirty_flag_inaccurate", "No pending events but dirty is true")
            )

    id_map_path = ctx.state_dir / "id-map.json"
    if id_map_path.exists():
        try:
            id_map = json.loads(id_map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(_finding("id_map_invalid", f"id-map.json is not valid JSON: {exc}"))
        else:
            for key, default in new_id_map().items():
                if not isinstance(default, dict):
                    continue
                if key in id_map and not isinstance(id_map[key], dict):
                    findings.append(_finding("id_map_invalid", f"id-map.{key} must be an object"))
    return findings
