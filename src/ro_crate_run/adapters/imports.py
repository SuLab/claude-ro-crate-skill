"""Import an existing RO-Crate by replaying its graph as journal events, so a
crate produced elsewhere can be folded into the current run's provenance."""

from __future__ import annotations

import json
from pathlib import Path


def _types(entity: dict[str, object]) -> list[str]:
    typ = entity.get("@type")
    return [str(t) for t in (typ if isinstance(typ, list) else [typ]) if t]


def import_existing_ro_crate(crate: Path) -> list[dict[str, object]]:
    """Import an existing RO-Crate, emitting events for workflows, actions, steps, params, files."""
    meta_path = crate / "ro-crate-metadata.json" if crate.is_dir() else crate
    if not meta_path.is_file():
        raise ValueError(
            f"no RO-Crate metadata found at {meta_path}; pass a crate directory or its "
            "ro-crate-metadata.json"
        )
    try:
        metadata = json.loads(meta_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{meta_path} is not valid JSON: {exc}") from exc
    if not isinstance(metadata, dict) or "@graph" not in metadata:
        raise ValueError(f"{meta_path} is not a valid RO-Crate (missing @graph)")
    events: list[dict[str, object]] = []
    for entity in metadata.get("@graph", []):
        if not isinstance(entity, dict) or "@id" not in entity:
            continue
        types = _types(entity)
        eid = str(entity["@id"])
        if "ComputationalWorkflow" in types:
            events.append({
                "event_type": "workflow.identified",
                "payload": {
                    "workflow_id": eid,
                    "path": eid,
                    "name": entity.get("name", eid),
                    "engine": "imported-ro-crate",
                },
            })
        elif any(t.endswith("Action") for t in types) and eid != "./":
            status = entity.get("actionStatus", {})
            failed = isinstance(status, dict) and "Failed" in str(status.get("@id", ""))
            # Emit a paired started BEFORE the terminal: the reducer only builds a
            # CommandRecord on execution.command.started, so a terminal-only import
            # would be dropped. The shared command_id also keeps recovery from
            # flagging this synthesized started as abandoned (its terminal matches).
            events.append({
                "event_type": "execution.command.started",
                "payload": {
                    "command_id": eid,
                    "action_id": eid,
                    "display_command": entity.get("name", eid),
                    "imported": True,
                },
            })
            events.append({
                "event_type": "execution.command.failed" if failed else "execution.command.completed",
                "payload": {
                    "command_id": eid,
                    "action_id": eid,
                    "display_command": entity.get("name", eid),
                    "exit_code": 1 if failed else 0,
                    "imported": True,
                },
            })
        elif "HowToStep" in types:
            events.append({
                "event_type": "workflow.step.identified",
                "payload": {"step_id": eid, "name": entity.get("name", eid)},
            })
        elif "FormalParameter" in types:
            events.append({
                "event_type": "workflow.parameter.declared",
                "payload": {
                    "name": entity.get("name", eid),
                    "formal_parameter": eid,
                    "value": "",
                },
            })
        elif ("File" in types or "Dataset" in types) and eid not in {"./", "ro-crate-metadata.json"}:
            events.append({
                "event_type": "file.observed",
                "payload": {"path": eid, "name": entity.get("name", eid)},
            })
    return events
