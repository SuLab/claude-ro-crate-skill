from __future__ import annotations

import json

from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .jsonld import _inline_contexts


def check_shacl(ctx: ValidationContext) -> list[ValidationFinding]:
    if not ctx.strict or ctx.metadata is None:
        return []
    try:
        import pyshacl
        from rdflib import Graph
    except ImportError:
        return []  # graceful: shacl extra not installed
    try:
        data = Graph()
        data.parse(data=json.dumps(_inline_contexts(ctx.metadata)), format="json-ld")
        # SPEC §20.1: only run SHACL when a shapes graph is available.
        # Calling pyshacl.validate(data, shacl_graph=None) validates data against
        # itself and always conforms — that is a false assurance, so we skip instead.
        shapes_graph = _load_shapes_graph()
        if shapes_graph is None:
            return []
        conforms, _results_graph, results_text = pyshacl.validate(
            data, shacl_graph=shapes_graph, inference="none", abort_on_first=False
        )
    except Exception as exc:
        return [ValidationFinding("ro_crate", "shacl_error", f"SHACL validation error: {exc}")]
    if not conforms:
        return [ValidationFinding("ro_crate", "shacl_nonconformant", f"SHACL non-conformance: {results_text[:500]}")]
    return []


def _load_shapes_graph() -> Graph | None:  # type: ignore[name-defined]  # noqa: F821
    """Return the SHACL shapes graph if one is bundled with the package, else None."""
    from importlib import resources as _resources

    try:
        from rdflib import Graph as _Graph

        shapes_ref = _resources.files("ro_crate_run.assets") / "ro-crate-shacl.ttl"
        shapes_text = shapes_ref.read_text(encoding="utf-8")
        g = _Graph()
        g.parse(data=shapes_text, format="turtle")
        return g
    except (FileNotFoundError, TypeError, AttributeError):
        return None
