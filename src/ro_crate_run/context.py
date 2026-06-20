"""Resolve the project root and the location of the ``.ro-crate-run`` state
directory from the current working directory, honouring the CLAUDE_PROJECT_DIR /
CLAUDE_PLUGIN_ROOT overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_STATE_DIR
from .git import git_toplevel


@dataclass(frozen=True)
class ProjectContext:
    cwd: Path
    project_dir: Path
    state_dir: Path
    plugin_root: Path | None = None
    skill_dir: Path | None = None

    @classmethod
    def from_cwd(
        cls, cwd: str | Path | None = None, env: dict[str, str] | None = None
    ) -> ProjectContext:
        env = env or dict(os.environ)
        raw_cwd = Path(cwd or os.getcwd())
        current = raw_cwd if raw_cwd.exists() else raw_cwd.parent
        current = current.resolve()
        project_dir = (
            Path(env["CLAUDE_PROJECT_DIR"]).resolve()
            if env.get("CLAUDE_PROJECT_DIR")
            else _discover_project(current)
        )
        plugin_root = (
            Path(env["CLAUDE_PLUGIN_ROOT"]).resolve()
            if env.get("CLAUDE_PLUGIN_ROOT")
            else _discover_plugin_root(current)
        )
        skill_dir = None
        if plugin_root is not None:
            skill_dir = plugin_root / "skills" / "ro-crate-run"
        else:
            skill_dir = project_dir / ".claude" / "skills" / "ro-crate-run"
        return cls(
            cwd=current,
            project_dir=project_dir,
            state_dir=project_dir / DEFAULT_STATE_DIR,
            plugin_root=plugin_root,
            skill_dir=skill_dir,
        )


def _discover_project(cwd: Path) -> Path:
    top = git_toplevel(cwd)
    if top:
        return Path(top).resolve()
    for path in [cwd, *cwd.parents]:
        if (path / ".git").exists():
            return path
    return cwd


def _discover_plugin_root(cwd: Path) -> Path | None:
    for path in [cwd, *cwd.parents]:
        if (path / ".claude-plugin" / "plugin.json").exists():
            return path
    return None
