from __future__ import annotations

import re
from pathlib import Path


def identify(path: Path) -> dict[str, object] | None:
    if path.suffix != ".nf" and path.name != "nextflow.config":
        return None
    steps = re.findall(r"process\s+(\w+)\s*\{", path.read_text())
    return {"engine": "nextflow", "path": str(path), "steps": steps}
