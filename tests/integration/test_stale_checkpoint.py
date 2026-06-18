from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.hooks import handle_hook
from ro_crate_run.state import load_state


def test_stop_hook_checkpoints_when_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # start with initial checkpoint
    assert main(["start", "Stale", "--mode", "monitored", "--profile", "process"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    # introduce a new provenance event -> dirty/stale
    assert main(["note", "later note", "--public"]) == 0
    assert load_state(state_dir).dirty is True

    result = handle_hook(
        "Stop", {"cwd": str(tmp_path)}, env={"CLAUDE_PROJECT_DIR": str(tmp_path)}
    )
    assert result.exit_code == 0, f"monitored Stop should not block a valid crate: {result.stderr}"
    after = load_state(state_dir)
    assert after.dirty is False
    assert after.last_checkpoint is not None
    assert after.last_checkpoint.materialized_through_sequence >= after.sequence - 3
    report = json.loads(
        (state_dir / "ro-crate" / "validation-report.json").read_text()
    )
    assert report["status"] in {"passed", "warning"}
