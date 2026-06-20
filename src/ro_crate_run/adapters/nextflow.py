"""Nextflow adapter: detect ``.nf`` / ``nextflow.config`` and list its processes."""

from __future__ import annotations

import re
from pathlib import Path

engine_name = "nextflow"
homepage = "https://www.nextflow.io/"

# Path patterns that name a Nextflow workflow definition (read by the registry seam).
SUFFIXES: tuple[str, ...] = (".nf",)
FILENAMES: tuple[str, ...] = ("nextflow.config",)


def identify(path: Path) -> dict[str, object] | None:
    if path.suffix not in SUFFIXES and path.name not in FILENAMES:
        return None
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        # Unreadable / non-UTF-8 file: skip rather than crash materialization.
        return None
    steps = re.findall(r"process\s+(\w+)\s*\{", text)
    return {"engine": engine_name, "path": str(path), "steps": steps}
