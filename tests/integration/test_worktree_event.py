from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.hooks import handle_hook
from ro_crate_run.state import read_events


def test_worktree_create_appends_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "WT", "--mode", "monitored", "--profile", "process"]) == 0
    handle_hook(
        "WorktreeCreate",
        {"cwd": str(tmp_path), "path": str(tmp_path / "wt")},
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    types = [e["event_type"] for e in read_events(tmp_path / ".ro-crate-run")]
    assert "git.worktree.created" in types
