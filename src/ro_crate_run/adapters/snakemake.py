"""Snakemake adapter: detect a ``Snakefile`` / ``.smk`` file and list its rules."""

from __future__ import annotations

from pathlib import Path

engine_name = "snakemake"
homepage = "https://snakemake.github.io/"

# Path patterns that name a Snakemake workflow definition (read by the registry seam).
SUFFIXES: tuple[str, ...] = (".smk",)
FILENAMES: tuple[str, ...] = ("Snakefile",)


def identify(path: Path) -> dict[str, object] | None:
    if path.name not in FILENAMES and path.suffix not in SUFFIXES:
        return None
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        # Unreadable / non-UTF-8 file: skip rather than crash materialization.
        return None
    steps = [
        line.split()[1].rstrip(":")
        for line in text.splitlines()
        if line.strip().startswith("rule ")
    ]
    return {"engine": engine_name, "path": str(path), "steps": steps}
