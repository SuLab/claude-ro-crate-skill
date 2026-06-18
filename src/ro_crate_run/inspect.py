from __future__ import annotations

import json
from pathlib import Path

from .state import read_events


def inspect_events(state_dir: Path) -> dict[str, object]:
    events = read_events(state_dir)
    return {
        "event_count": len(events),
        "event_types": sorted({str(event["event_type"]) for event in events}),
        "first_sequence": events[0]["sequence"] if events else None,
        "last_sequence": events[-1]["sequence"] if events else None,
    }


def inspect_crate(state_dir: Path) -> dict[str, object]:
    metadata = json.loads((state_dir / "ro-crate" / "ro-crate-metadata.json").read_text())
    root = next(entity for entity in metadata["@graph"] if entity["@id"] == "./")
    actions = [entity for entity in metadata["@graph"] if "Action" in str(entity.get("@type"))]
    files = [
        entity
        for entity in metadata["@graph"]
        if entity.get("@type") == "File"
        or (isinstance(entity.get("@type"), list) and "File" in entity["@type"])
    ]
    return {
        "name": root["name"],
        "profile": root["conformsTo"],
        "action_count": len(actions),
        "file_count": len(files),
    }


def mermaid_graph(state_dir: Path) -> str:
    metadata_path = state_dir / "ro-crate" / "ro-crate-metadata.json"
    if not metadata_path.exists():
        return "graph TD\n"
    metadata = json.loads(metadata_path.read_text())
    graph = metadata.get("@graph", [])
    lines = ["graph TD"]
    edges: list[str] = []

    def node_id(raw: str) -> str:
        return (
            "n_"
            + str(raw)
            .replace(".", "_")
            .replace("/", "_")
            .replace("-", "_")
            .replace(":", "_")
        )

    def is_action(entity: dict[str, object]) -> bool:
        types = entity.get("@type")
        values = types if isinstance(types, list) else [types]
        return any(str(value).endswith("Action") for value in values)

    for entity in graph:
        entity_id = str(entity.get("@id"))
        if is_action(entity):
            label = str(entity.get("name", entity_id))
            lines.append(f'  {node_id(entity_id)}["{label}"]')
            for obj in _as_refs(entity.get("object")):
                edges.append(f'  {node_id(obj)}["{obj}"] --> {node_id(entity_id)}')
            for res in _as_refs(entity.get("result")):
                edges.append(f'  {node_id(entity_id)} --> {node_id(res)}["{res}"]')
            for inst in _as_refs(entity.get("instrument")):
                edges.append(f"  {node_id(inst)} -. instrument .-> {node_id(entity_id)}")
    lines.extend(sorted(set(edges)))
    return "\n".join(lines) + "\n"


def _as_refs(value: object) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    refs: list[str] = []
    for item in items:
        if isinstance(item, dict) and "@id" in item:
            refs.append(str(item["@id"]))
    return refs
