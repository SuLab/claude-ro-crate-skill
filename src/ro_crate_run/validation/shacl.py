"""Optional SHACL validation (strict mode only): validate the crate against the
bundled shapes graph when pyshacl and a shapes graph are available. Findings are
filed under the ``ro_crate`` level, and a missing pyshacl or shapes graph
degrades gracefully to no findings."""

from __future__ import annotations

from rdflib import Graph

from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .jsonld import build_graph


def check_shacl(ctx: ValidationContext) -> list[ValidationFinding]:
    if not ctx.strict or ctx.metadata is None:
        return []
    try:
        import pyshacl
    except ImportError:
        return []  # graceful: shacl extra not installed
    try:
        # Build the data graph through the shared JSON-LD seam so context inlining
        # and parsing live in one place; a parse failure here is reported as a
        # SHACL error (the L2 ro_crate checker separately reports jsonld_expansion_failed).
        data, build_error = build_graph(ctx.metadata)
        if build_error is not None or data is None:
            raise ValueError(build_error or "could not build data graph")
        # Only run SHACL when a shapes graph is available.
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


def _load_shapes_graph() -> Graph | None:
    """Return the SHACL shapes graph if one is bundled with the package, else None."""
    from importlib import resources as _resources

    try:
        shapes_ref = _resources.files("ro_crate_run.assets") / "ro-crate-shacl.ttl"
        shapes_text = shapes_ref.read_text(encoding="utf-8")
        g = Graph()
        g.parse(data=shapes_text, format="turtle")
        return g
    except (FileNotFoundError, TypeError, AttributeError):
        return None
