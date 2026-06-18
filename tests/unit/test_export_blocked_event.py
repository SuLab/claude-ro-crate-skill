"""A blocked public export fails closed AND records a run.export.blocked event (SPEC §13.4)."""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main


def test_blocked_public_export_emits_event(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "T", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    (tmp_path / "leak.txt").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nAKIAIOSFODNN7EXAMPLE\n"
    )
    assert main(["output", "leak.txt", "--role", "result", "--copy"]) == 0
    assert main(["run", "--", "python3", "-c", "print('x')"]) == 0
    assert main(["checkpoint"]) == 0
    assert main(["finalize", "--public", "--zip"]) == 1  # gate fails closed
    events = [
        json.loads(line)
        for line in (tmp_path / ".ro-crate-run" / "events.ndjson").read_text().splitlines()
        if line.strip()
    ]
    assert any(e["event_type"] == "run.export.blocked" for e in events), \
        "blocked export did not record a run.export.blocked event"
    # Nothing shipped.
    assert not list(tmp_path.rglob("*.zip")), "a zip was produced despite the gate block"
