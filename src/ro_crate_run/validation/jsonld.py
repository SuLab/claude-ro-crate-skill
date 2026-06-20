"""JSON-LD expansion for level-2 validation: inline the vendored RO-Crate and
workflow-run contexts so a crate expands against pinned term definitions, then
count the resulting RDF triples."""

from __future__ import annotations

import copy
import json
from functools import cache
from importlib import resources
from typing import Any

from rdflib import Graph

_CONTEXT_FILES = {
    "https://w3id.org/ro/crate/1.2/context": "ro-crate-1.2.jsonld",
    "https://w3id.org/ro/terms/workflow-run/context": "workflow-run.jsonld",
}


@cache
def _load_context(uri: str) -> Any:
    filename = _CONTEXT_FILES[uri]
    text = (resources.files("ro_crate_run") / "assets" / "contexts" / filename).read_text(encoding="utf-8")
    return json.loads(text)["@context"]


def _inline_contexts(metadata: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(metadata)
    ctx = data.get("@context")
    items = ctx if isinstance(ctx, list) else [ctx]
    resolved: list[Any] = []
    for item in items:
        if isinstance(item, str) and item in _CONTEXT_FILES:
            resolved.append(_load_context(item))
        else:
            resolved.append(item)
    data["@context"] = resolved
    return data


def expand_metadata(metadata: dict[str, Any]) -> tuple[int, str | None]:
    try:
        inlined = _inline_contexts(metadata)
        graph = Graph()
        graph.parse(data=json.dumps(inlined), format="json-ld")
        return len(graph), None
    except Exception as exc:
        return 0, str(exc)
