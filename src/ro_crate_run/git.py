"""Capture git working-tree state and diffs for provenance, degrading to a
not-available marker when the directory is not a git repository."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(args: list[str], cwd: Path) -> str | None:
    """Run ``git <args>`` in ``cwd`` and return its stripped stdout.

    Returns ``None`` when git is unavailable or the command exits non-zero
    (e.g. the directory is not a git repository).
    """
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True, capture_output=True, check=False
        )
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def capture_diff(project_dir: Path) -> str | None:
    """Return ``git diff HEAD`` output or ``None`` if the directory is not a git repo."""
    return _git(["diff", "HEAD"], project_dir)


def observe_git_state(project_dir: Path) -> dict[str, object]:
    """Snapshot the repository: root, porcelain status, dirty flag, commit/branch/remote.

    Returns ``{"available": False}`` when ``project_dir`` is not inside a git repo.
    """
    top = _git(["rev-parse", "--show-toplevel"], project_dir)
    if not top:
        return {"available": False}
    porcelain = _git(["status", "--porcelain"], project_dir) or ""
    state: dict[str, object] = {
        "available": True,
        "root": top,
        "status": porcelain,
        # Explicit dirty flag: the reproducibility validator (require_clean_git) keys on it.
        "dirty": bool(porcelain.strip()),
    }
    # Omit absent fields rather than storing None: event payloads reject JSON null,
    # and a repo with no commit/remote (e.g. fresh `git init`) must not crash start.
    for key, value in (
        ("commit", _git(["rev-parse", "HEAD"], project_dir)),
        ("branch", _git(["branch", "--show-current"], project_dir)),
        ("remote", _git(["config", "--get", "remote.origin.url"], project_dir)),
    ):
        if value:
            state[key] = value
    return state
