from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.cli import main


def test_failed_command_records_failed_action_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Fail", "--mode", "monitored", "--profile", "process"]) == 0
    rc = main(
        ["run", "--", "python3", "-c",
         "import sys; sys.stderr.write('explode\\n'); sys.exit(7)"]
    )
    assert rc == 7
    assert main(["checkpoint", "--profile", "process"]) in {0, 1}

    state_dir = tmp_path / ".ro-crate-run"
    # stderr log captured on disk
    logs = list((state_dir / "logs").glob("*.stderr.txt"))
    assert logs, "no stderr log file found"
    assert "explode" in logs[0].read_text()
    # failed action present in the crate
    meta = json.loads((state_dir / "ro-crate" / "ro-crate-metadata.json").read_text())
    statuses = [
        e.get("actionStatus", {}).get("@id", "")
        for e in meta["@graph"]
        if str(e.get("@type", "")).endswith("Action")
    ]
    assert any("FailedActionStatus" in s for s in statuses)
