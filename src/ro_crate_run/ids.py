"""Stable crate `@id` construction: slugged entity ids, project-relative
file ids, and the canonical id-map skeleton persisted as id-map.json."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .fs import write_json

ID_MAP_SCHEMA_VERSION = "1.0.0"


def relative_file_id(path: Path, project_dir: Path) -> str:
    """Return the crate `@id` for a file path.

    An absolute path inside the project becomes a project-relative path; an
    absolute path outside the project becomes a ``file://`` URI; a relative
    path is returned unchanged.
    """
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(project_dir.resolve()))
        except ValueError:
            return path.as_uri()
    return str(path)


def file_ref(path: Path, project_dir: Path) -> dict[str, str]:
    """Return a `{"@id": ...}` reference using :func:`relative_file_id`."""
    return {"@id": relative_file_id(path, project_dir)}


def new_id_map() -> dict[str, Any]:
    """Return a fresh id-map skeleton with every persisted key set empty.

    The skeleton is the union of every id-map seeder in the package, so all
    consumers project from one canonical shape.
    """
    return {
        "schema_version": ID_MAP_SCHEMA_VERSION,
        "event_to_entity": {},
        "path_to_entity": {},
        "step_to_entity": {},
        "profile_to_entity": {},
        "software_to_entity": {},
    }


def slugify(value: str) -> str:
    """Normalise ``value`` into a stable, collision-free ``@id`` fragment.

    Lowercases, collapses each run of characters outside ``[a-zA-Z0-9._-]`` into a
    single ``-`` (``.`` and ``_`` are preserved), and trims leading/trailing ``-``.
    An empty result falls back to the literal ``item`` so callers always get a
    non-empty, well-formed fragment to embed in a crate ``@id``.
    """
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def software_entity_id(name: str) -> str:
    """Return a stable ``#software/<slug>`` id for the given software name."""
    return f"#software/{slugify(name)}"


def step_entity_id(step_id: str) -> str:
    """Return a stable ``#step/<slug>`` id for the given workflow step id."""
    return f"#step/{slugify(step_id)}"


class IdMap:
    """Persisted allocator/cache mapping events, steps, and software to crate ids.

    Backed by id-map.json under the state dir; a missing file starts from the
    canonical :func:`new_id_map` skeleton. The cache is derived, never a source
    of truth.
    """

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "id-map.json"
        if self.path.exists():
            self.data: dict[str, Any] = json.loads(self.path.read_text())
        else:
            self.data = new_id_map()

    def entity_for_event(self, event_id: str, kind: str = "action") -> str:
        """Return the urn:uuid for an event, minting and persisting on first use.

        Keyed by ``{kind}:{event_id}`` so the same event id can carry distinct
        ids per kind (callers pass ``control`` alongside the default ``action``).
        """
        key = f"{kind}:{event_id}"
        mapping = self.data.setdefault("event_to_entity", {})
        if key not in mapping:
            mapping[key] = f"urn:uuid:{uuid.uuid4()}"
            self.save()
        return str(mapping[key])

    def entity_for_step(self, step_id: str) -> str:
        """Return the cached ``#step/<slug>`` id for a step, persisting on first use."""
        mapping = self.data.setdefault("step_to_entity", {})
        if step_id not in mapping:
            mapping[step_id] = step_entity_id(step_id)
            self.save()
        return str(mapping[step_id])

    def software_id(self, name: str) -> str:
        """Return the cached ``#software/<slug>`` id for software, persisting on first use.

        Named to match the ``entity_for_*`` accessors and to avoid shadowing the
        module-level :func:`software_entity_id` free function it delegates to.
        """
        mapping = self.data.setdefault("software_to_entity", {})
        if name not in mapping:
            mapping[name] = software_entity_id(name)
            self.save()
        return str(mapping[name])

    def save(self) -> None:
        """Write id-map.json in the canonical deterministic JSON form."""
        write_json(self.path, self.data)
