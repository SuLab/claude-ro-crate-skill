from __future__ import annotations

from pathlib import Path


def identify(path: Path) -> dict[str, object] | None:
    if path.suffix != ".cwl":
        return None
    text = path.read_text()
    steps: list[str] = []
    in_steps = False
    for line in text.splitlines():
        if line.startswith("steps:"):
            in_steps = True
            continue
        if in_steps:
            if line and not line[0].isspace():
                break
            stripped = line.strip()
            if stripped.endswith(":") and not stripped.startswith("#"):
                steps.append(stripped.rstrip(":"))
    return {"engine": "cwl", "path": str(path), "steps": steps}
