from __future__ import annotations

import subprocess
from pathlib import Path


def capture_diff(project_dir: Path) -> str | None:
    """Return ``git diff HEAD`` output or ``None`` if the directory is not a git repo."""
    out = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=str(project_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    return out.stdout or ""


def observe_git_state(project_dir: Path) -> dict[str, object]:
    def run(args: list[str]) -> str | None:
        out = subprocess.run(
            ["git", *args], cwd=str(project_dir), text=True, capture_output=True, check=False
        )
        return out.stdout.strip() if out.returncode == 0 else None

    top = run(["rev-parse", "--show-toplevel"])
    if not top:
        return {"available": False}
    state: dict[str, object] = {
        "available": True,
        "root": top,
        "status": run(["status", "--porcelain"]) or "",
    }
    # Omit absent fields rather than storing None: event payloads reject JSON null,
    # and a repo with no commit/remote (e.g. fresh `git init`) must not crash start.
    for key, value in (
        ("commit", run(["rev-parse", "HEAD"])),
        ("branch", run(["branch", "--show-current"])),
        ("remote", run(["config", "--get", "remote.origin.url"])),
    ):
        if value:
            state[key] = value
    return state
