from __future__ import annotations

import json
from pathlib import Path


def _types(entity: dict[str, object]) -> list[str]:
    typ = entity.get("@type")
    return [str(t) for t in (typ if isinstance(typ, list) else [typ]) if t]


def import_existing_ro_crate(crate: Path) -> list[dict[str, object]]:
    """Import an existing RO-Crate, emitting events for workflows, actions, steps, params, files."""
    metadata = json.loads((crate / "ro-crate-metadata.json").read_text())
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
                    "confidence": "high",
                },
            })
        elif any(t.endswith("Action") for t in types) and eid != "./":
            status = entity.get("actionStatus", {})
            failed = isinstance(status, dict) and "Failed" in str(status.get("@id", ""))
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
