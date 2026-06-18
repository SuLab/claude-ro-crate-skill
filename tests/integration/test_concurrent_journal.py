"""Concurrent CLI invocations must not corrupt the hash-chained journal.

Each `rcr` startup runs ensure_recovered(); before recovery was serialized under the
append lock, concurrent recoveries raced appends (and each other) and produced sequence
gaps / hash-chain breaks. Real Claude sessions fire many hooks concurrently, so this is
a production integrity property, not just a test concern.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.validation.validator import validate_run


def test_concurrent_appends_keep_journal_consistent(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "C", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    code = "from ro_crate_run.cli import main as m; raise SystemExit(m(['note', 'concurrent']))"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code], cwd=tmp_path, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(16)
    ]
    for p in procs:
        assert p.wait() == 0

    report = validate_run(tmp_path / ".ro-crate-run", strict=False, public=False, append_event=False)
    assert report.levels["journal"] == "passed", [e.__dict__ for e in report.errors]
    assert report.levels["state"] == "passed", [e.__dict__ for e in report.errors]

    events = [
        json.loads(line)
        for line in (tmp_path / ".ro-crate-run" / "events.ndjson").read_text().splitlines()
        if line.strip()
    ]
    seqs = sorted(e["sequence"] for e in events)
    assert seqs == list(range(1, len(seqs) + 1)), f"sequence gaps/dups: {seqs}"
    # All 16 concurrent notes landed.
    notes = [e for e in events if e["event_type"] == "human.note"]
    assert len(notes) == 16, f"expected 16 notes, got {len(notes)}"
