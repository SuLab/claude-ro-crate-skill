"""Hook auto-start: capture the agent's actions even without an explicit `rcr start`."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ro_crate_run.hooks import handle_hook


def _events(state_dir: Path) -> list[dict]:
    p = state_dir / "events.ndjson"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_auto_start_bootstraps_run_and_captures_prompt(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "RCR_AUTO_START": "1"}
    sd = tmp_path / ".ro-crate-run"
    assert not (sd / "state.json").exists()

    handle_hook("UserPromptSubmit", {"prompt": "do the thing", "cwd": str(tmp_path)}, env=env)

    assert (sd / "state.json").exists(), "auto-start did not bootstrap a run"
    types = [e["event_type"] for e in _events(sd)]
    assert "run.started" in types, "no run.started from auto-start"
    assert "human.prompt" in types, "the triggering prompt was not captured"


def test_no_auto_start_without_env_flag(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}  # no RCR_AUTO_START
    handle_hook("UserPromptSubmit", {"prompt": "x", "cwd": str(tmp_path)}, env=env)
    assert not (tmp_path / ".ro-crate-run" / "state.json").exists(), \
        "a run was created without RCR_AUTO_START"
