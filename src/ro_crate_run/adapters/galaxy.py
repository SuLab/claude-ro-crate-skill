"""Galaxy adapter: detect a ``.ga`` workflow export and list its step names."""

from __future__ import annotations

import json
from pathlib import Path

engine_name = "galaxy"
homepage = "https://galaxyproject.org/"

# Path patterns that name a Galaxy workflow export (read by the registry seam).
SUFFIXES: tuple[str, ...] = (".ga",)
FILENAMES: tuple[str, ...] = ()


def identify(path: Path) -> dict[str, object] | None:
    if path.suffix not in SUFFIXES:
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # Unreadable / non-UTF-8 / malformed file: skip rather than crash.
        return None
    if not isinstance(data, dict) or "a_galaxy_workflow" not in data:
        return None
    steps = [str(v.get("name", k)) for k, v in (data.get("steps") or {}).items()]
    return {"engine": engine_name, "path": str(path), "steps": steps}
