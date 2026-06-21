"""Common Workflow Language adapter: detect a ``.cwl`` workflow and list its steps."""

from __future__ import annotations

from pathlib import Path

from . import path_matches

engine_name = "cwl"
homepage = "https://www.commonwl.org/"

# Path patterns that name a CWL workflow definition.
SUFFIXES: tuple[str, ...] = (".cwl",)
FILENAMES: tuple[str, ...] = ()


def identify(path: Path) -> dict[str, object] | None:
    """Return ``{engine, steps}`` for a ``.cwl`` workflow (steps = step names),
    or ``None`` if ``path`` is not a CWL definition or cannot be read."""
    if not path_matches(path, SUFFIXES, FILENAMES):
        return None
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        # Unreadable / non-UTF-8 file: skip rather than crash materialization.
        return None
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
    return {"engine": engine_name, "steps": steps}
