"""Workflow-engine adapters: detect a workflow definition file, name its engine,
and supply the engine's homepage for the crate's engine SoftwareApplication.

Each adapter exposes the `WorkflowAdapter` Protocol (an ``identify`` callable
plus ``engine_name`` / ``homepage`` attributes). All adapters are registered in
the single `ADAPTERS` list; the homepage lookup is derived from it so a new
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
    ``url``; ``identify`` returns ``{engine, path, steps}`` or ``None``.
    """

    engine_name: str
    homepage: str

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
