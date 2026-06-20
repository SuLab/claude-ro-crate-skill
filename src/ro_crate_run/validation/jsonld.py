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

from ro_crate_run.constants import RO_CRATE_CONTEXT, WORKFLOW_RUN_CONTEXT

# Maps each context URI the materializer emits to its vendored definition file.
# Keyed by the shared constants (the same URIs builder.py writes into @context) so
# validation expands against exactly the contexts the crate declares.
_CONTEXT_FILES = {
    RO_CRATE_CONTEXT: "ro-crate-1.2.jsonld",
    WORKFLOW_RUN_CONTEXT: "workflow-run.jsonld",
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


def build_graph(metadata: dict[str, Any]) -> tuple[Graph | None, str | None]:
    """Inline the vendored contexts and parse the crate metadata into an rdflib
    Graph. Returns ``(graph, None)`` on success or ``(None, error)`` if the
    JSON-LD does not parse. This is the single public JSON-LD → Graph seam; both
    triple counting (``expand_metadata``) and SHACL build on it instead of
    re-running ``Graph().parse`` against the private context-inlining helper.
    """
    try:
        inlined = _inline_contexts(metadata)
        graph = Graph()
        graph.parse(data=json.dumps(inlined), format="json-ld")
        return graph, None
    except Exception as exc:
        return None, str(exc)


def expand_metadata(metadata: dict[str, Any]) -> tuple[int, str | None]:
    """Expand the crate against the vendored contexts and return ``(triple_count,
    error)`` — ``(0, message)`` when the JSON-LD fails to parse."""
    graph, error = build_graph(metadata)
    if error is not None or graph is None:
        return 0, error
    return len(graph), None
