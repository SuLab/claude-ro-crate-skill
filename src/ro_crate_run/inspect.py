"""Read-only inspection helpers: summarise the event journal or the emitted
crate, and render a Mermaid graph of the crate's actions and their data flow."""

from __future__ import annotations

import json
from pathlib import Path

from .state import read_events
from .validation.graphview import as_list, is_action, types_of

# Returned by inspect_crate when no crate has been materialized yet, so the CLI
# prints a clear message instead of an uncaught FileNotFoundError reaching it.
_NO_CRATE = {"error": "no crate; run rcr checkpoint"}


def inspect_events(state_dir: Path) -> dict[str, object]:
    events = read_events(state_dir)
    return {
        "event_count": len(events),
        "event_types": sorted({str(event["event_type"]) for event in events}),
        "first_sequence": events[0]["sequence"] if events else None,
        "last_sequence": events[-1]["sequence"] if events else None,
    }


def inspect_crate(state_dir: Path) -> dict[str, object]:
    metadata_path = state_dir / "ro-crate" / "ro-crate-metadata.json"
    # Guard the missing manifest the same way mermaid_graph does: a run that has
    # never checkpointed has no crate, so report cleanly rather than raising.
    if not metadata_path.exists():
        return dict(_NO_CRATE)
    metadata = json.loads(metadata_path.read_text())
    root = next(entity for entity in metadata["@graph"] if entity["@id"] == "./")
    # Action/File membership routes through the shared @type-normalization helpers
    # so this inspector and the validators agree on detection (e.g. scalar-or-list
    # @type, *Action by suffix rather than a loose substring match).
    actions = [entity for entity in metadata["@graph"] if is_action(entity)]
    files = [entity for entity in metadata["@graph"] if "File" in types_of(entity)]
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
    """Extract ``@id`` strings from a scalar-or-list JSON-LD reference value,
    coercing to a list via the shared graphview helper and dropping non-refs."""
    if value is None:
        return []
    refs: list[str] = []
    for item in as_list(value):
        if isinstance(item, dict) and "@id" in item:
            refs.append(str(item["@id"]))
    return refs
