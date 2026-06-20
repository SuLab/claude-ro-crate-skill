"""Stable crate `@id` construction: slugged entity ids, project-relative
file ids, and the canonical id-map skeleton persisted as id-map.json."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

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
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def software_entity_id(name: str) -> str:
    """Return a stable ``#software/<slug>`` id for the given software name."""
    return f"#software/{slugify(name)}"


class IdMap:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "id-map.json"
        if self.path.exists():
            self.data: dict[str, Any] = json.loads(self.path.read_text())
        else:
            self.data = {
                "schema_version": "1.0.0",
                "event_to_entity": {},
                "path_to_entity": {},
                "step_to_entity": {},
                "profile_to_entity": {},
                "software_to_entity": {},
            }

    def entity_for_event(self, event_id: str, kind: str = "action") -> str:
        key = f"{kind}:{event_id}"
        mapping = self.data.setdefault("event_to_entity", {})
        if key not in mapping:
            mapping[key] = f"urn:uuid:{uuid.uuid4()}"
            self.save()
        return str(mapping[key])

    def entity_for_path(self, path: str) -> str:
        mapping = self.data.setdefault("path_to_entity", {})
        if path not in mapping:
            mapping[path] = path
            self.save()
        return str(mapping[path])

    def entity_for_step(self, step_id: str) -> str:
        mapping = self.data.setdefault("step_to_entity", {})
        if step_id not in mapping:
            mapping[step_id] = f"#step/{slugify(step_id)}"
            self.save()
        return str(mapping[step_id])

    def software_entity_id(self, name: str) -> str:
        mapping = self.data.setdefault("software_to_entity", {})
        if name not in mapping:
            mapping[name] = f"#software/{slugify(name)}"
            self.save()
        return str(mapping[name])

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")
