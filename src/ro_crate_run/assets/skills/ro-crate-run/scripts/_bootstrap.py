"""Stdlib-only path shim: make `ro_crate_run` importable for wrapper scripts.

Imported (``import _bootstrap``) by sibling wrapper scripts BEFORE they import
``ro_crate_run``. Resolution order: CLAUDE_PLUGIN_ROOT, then CLAUDE_PROJECT_DIR,
then a walk up from this file's own location. Each candidate is probed for
``ro_crate_run/__init__.py`` under the candidate itself, ``src/``, or ``.claude/lib/``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SUBDIRS = ("", "src", ".claude/lib")


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value))
    here = Path(__file__).resolve()
    roots.extend(here.parents)
    return roots


def find_package_root() -> Path | None:
    for root in _candidate_roots():
        for sub in _SUBDIRS:
            candidate = (root / sub) if sub else root
            if (candidate / "ro_crate_run" / "__init__.py").exists():
                return candidate
    return None


def ensure_on_path() -> None:
    try:
        import ro_crate_run  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    found = find_package_root()
    if found is not None and str(found) not in sys.path:
        sys.path.insert(0, str(found))


ensure_on_path()
