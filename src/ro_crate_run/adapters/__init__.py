"""Workflow-engine adapters: detect a workflow definition file, name its engine,
and supply the engine's homepage for the crate's engine SoftwareApplication.

Each adapter exposes the `WorkflowAdapter` Protocol (an ``identify`` callable,
``engine_name`` / ``homepage`` attributes, and the ``SUFFIXES`` / ``FILENAMES``
that name its workflow-definition files). All adapters are registered in the
single `ADAPTERS` list; the homepage lookup and the path-only detection seam
(`engine_for_path` / `is_workflow_definition`) are derived from it, so a new
engine is added in exactly one place."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from . import cwl, galaxy, nextflow, snakemake


@runtime_checkable
class WorkflowAdapter(Protocol):
    """A workflow-engine adapter.

    ``engine_name`` is the engine identifier emitted in ``identify``'s result;
    ``homepage`` is the engine's canonical URL used for its SoftwareApplication
    ``url``; ``SUFFIXES`` / ``FILENAMES`` declare the path patterns that name a
    workflow definition for this engine (used by the path-only detection seam);
    ``identify`` returns ``{engine, path, steps}`` or ``None``.
    """

    engine_name: str
    homepage: str
    SUFFIXES: tuple[str, ...]
    FILENAMES: tuple[str, ...]

    def identify(self, path: Path) -> dict[str, object] | None: ...


ADAPTERS: tuple[WorkflowAdapter, ...] = (
    cast(WorkflowAdapter, snakemake),
    cast(WorkflowAdapter, cwl),
    cast(WorkflowAdapter, nextflow),
    cast(WorkflowAdapter, galaxy),
)

# Engine names produced outside the file-detection adapters that still need a
# homepage decision. An imported RO-Crate names no executing engine, so its
# engine SoftwareApplication has no canonical homepage.
_EXTRA_ENGINE_HOMEPAGES: dict[str, str | None] = {
    "imported-ro-crate": None,
}

ENGINE_HOMEPAGES: dict[str, str | None] = {
    adapter.engine_name: adapter.homepage for adapter in ADAPTERS
}
ENGINE_HOMEPAGES.update(_EXTRA_ENGINE_HOMEPAGES)


def engine_homepage(name: str) -> str | None:
    """Return the canonical homepage URL for an engine name, or ``None``.

    ``None`` is returned both for engines with no canonical homepage (e.g. an
    imported RO-Crate) and for unknown engine names.
    """
    return ENGINE_HOMEPAGES.get(name)


def engine_for_path(path: Path) -> str | None:
    """Return the engine name for a workflow-definition path, or ``None``.

    Pure path-string logic over each adapter's declared ``SUFFIXES`` /
    ``FILENAMES`` — no filesystem reads — so the run-model reducer stays
    filesystem-free. Only engines with a registered adapter are ever returned;
    a path with no matching adapter (including ``.wdl``, which has no adapter)
    yields ``None``.
    """
    for adapter in ADAPTERS:
        if path.suffix in adapter.SUFFIXES or path.name in adapter.FILENAMES:
            return adapter.engine_name
    return None


def is_workflow_definition(path: Path) -> bool:
    """Return whether ``path`` names a workflow definition any adapter recognizes.

    Pure path-string logic (no filesystem reads), derived from the same per-adapter
    ``SUFFIXES`` / ``FILENAMES`` declarations as ``engine_for_path``.
    """
    return engine_for_path(path) is not None


def detect_engine(path: Path) -> dict[str, object] | None:
    """Return the first adapter's ``identify`` result for ``path``, or ``None``."""
    for adapter in ADAPTERS:
        raw = adapter.identify(path)
        if raw is not None:
            return raw
    return None


def extract_steps(path: Path) -> list[str]:
    """Return the step names a workflow definition declares, or an empty list."""
    result = detect_engine(path)
    if result is None:
        return []
    steps = result.get("steps", [])
    return list(steps) if isinstance(steps, list) else []
