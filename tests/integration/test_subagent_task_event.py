from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.hooks import handle_hook
from ro_crate_run.state import read_events


def test_subagent_and_task_events_appended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Agents", "--mode", "monitored", "--profile", "process"]) == 0
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    handle_hook("TaskCreated", {"cwd": str(tmp_path), "task_id": "t1"}, env=env)
    handle_hook("SubagentStart", {"cwd": str(tmp_path), "subagent": "explore"}, env=env)
    handle_hook("SubagentStop", {"cwd": str(tmp_path), "subagent": "explore"}, env=env)
    types = [e["event_type"] for e in read_events(tmp_path / ".ro-crate-run")]
    assert "agent.task.created" in types
    assert "agent.subagent.started" in types
    assert "agent.subagent.completed" in types
