"""Nextflow adapter: detect ``.nf`` / ``nextflow.config`` and list its processes."""

from __future__ import annotations

import re
from pathlib import Path

from . import path_matches

engine_name = "nextflow"
homepage = "https://www.nextflow.io/"

# Path patterns that name a Nextflow workflow definition.
SUFFIXES: tuple[str, ...] = (".nf",)
FILENAMES: tuple[str, ...] = ("nextflow.config",)


def identify(path: Path) -> dict[str, object] | None:
    """Return ``{engine, steps}`` for a ``.nf`` / ``nextflow.config`` file (steps =
    process names), or ``None`` if ``path`` is not a Nextflow definition or cannot be read."""
    if not path_matches(path, SUFFIXES, FILENAMES):
        return None
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        # Unreadable / non-UTF-8 file: skip rather than crash materialization.
        return None
    steps = re.findall(r"process\s+(\w+)\s*\{", text)
    return {"engine": engine_name, "steps": steps}
