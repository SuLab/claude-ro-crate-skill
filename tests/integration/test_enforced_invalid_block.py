from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.hooks import handle_hook


def test_enforced_stop_blocks_missing_required_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Enf", "--mode", "enforced", "--profile", "process"]) == 0
    # declare a required output that is never produced -> validation error
    assert main(["output", "missing.txt", "--role", "result", "--required"]) == 0

    result = handle_hook(
        "Stop", {"cwd": str(tmp_path)}, env={"CLAUDE_PROJECT_DIR": str(tmp_path)}
    )
    assert result.exit_code == 2
    assert "missing" in result.stderr.lower()
