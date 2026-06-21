"""Snakemake adapter: detect a ``Snakefile`` / ``.smk`` file and list its rules."""

from __future__ import annotations

from pathlib import Path

from . import path_matches

engine_name = "snakemake"
homepage = "https://snakemake.github.io/"

# Path patterns that name a Snakemake workflow definition.
SUFFIXES: tuple[str, ...] = (".smk",)
FILENAMES: tuple[str, ...] = ("Snakefile",)


def identify(path: Path) -> dict[str, object] | None:
    """Return ``{engine, steps}`` for a ``Snakefile`` / ``.smk`` file (steps =
    rule names), or ``None`` if ``path`` is not a Snakemake definition or cannot be read."""
    if not path_matches(path, SUFFIXES, FILENAMES):
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
