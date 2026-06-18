from __future__ import annotations

import json
from pathlib import Path


def identify(path: Path) -> dict[str, object] | None:
    if path.suffix != ".ga":
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "a_galaxy_workflow" not in data:
        return None
    steps = [str(v.get("name", k)) for k, v in (data.get("steps") or {}).items()]
    return {"engine": "galaxy", "path": str(path), "steps": steps}
