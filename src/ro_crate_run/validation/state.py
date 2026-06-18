from __future__ import annotations

import json

from ro_crate_run.models import ValidationFinding

from .context import ValidationContext

_BOOKKEEPING_PREFIXES = ("crate.checkpoint", "crate.validation")


def check_state(ctx: ValidationContext) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    state, events = ctx.state, ctx.events

    for event in events:
        if event.get("run_id") != state.run_id:
            findings.append(ValidationFinding("state", "run_id_mismatch", "Event run_id does not match state"))
            break

    if events:
        journal_hash = events[-1].get("event_hash")
        if state.last_event_hash != journal_hash:
            findings.append(
                ValidationFinding("state", "state_hash_mismatch", "state.last_event_hash does not match journal")
            )
        if state.sequence != len(events):
            findings.append(
                ValidationFinding("state", "state_sequence_mismatch", "state.sequence does not match journal length")
            )

    if state.current_phase_id:
        findings.append(ValidationFinding("state", "open_phase", f"Run has open phase {state.current_phase_id}"))
    if state.current_step_id:
        findings.append(ValidationFinding("state", "open_step", f"Run has open step {state.current_step_id}"))

    lc = state.last_checkpoint
    if lc is not None:
        if lc.materialized_through_sequence > state.sequence or lc.event_sequence > state.sequence:
            findings.append(
                ValidationFinding("state", "checkpoint_sequence_invalid", "last_checkpoint sequence exceeds journal")
            )

    # Dirty-flag accuracy: only meaningful when a prior checkpoint exists.
    if lc is not None:
        through = lc.materialized_through_sequence
        pending = any(
            int(e.get("sequence", 0)) > through
            and not str(e.get("event_type", "")).startswith(_BOOKKEEPING_PREFIXES)
            for e in events
        )
        if pending and not state.dirty:
            findings.append(
                ValidationFinding(
                    "state", "dirty_flag_inaccurate", "Uncheckpointed events exist but dirty is false"
                )
            )
        if not pending and state.dirty and lc.validation_status != "failed":
            findings.append(
                ValidationFinding(
                    "state", "dirty_flag_inaccurate", "No pending events but dirty is true"
                )
            )

    id_map_path = ctx.state_dir / "id-map.json"
    if id_map_path.exists():
        try:
            id_map = json.loads(id_map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(ValidationFinding("state", "id_map_invalid", f"id-map.json is not valid JSON: {exc}"))
        else:
            for key in ("event_to_entity", "path_to_entity", "step_to_entity"):
                if key in id_map and not isinstance(id_map[key], dict):
                    findings.append(ValidationFinding("state", "id_map_invalid", f"id-map.{key} must be an object"))
    return findings
