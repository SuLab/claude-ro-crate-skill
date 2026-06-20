from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run import commands
from ro_crate_run.redact import redact_run
from ro_crate_run.state import read_events


def _append_raw_line(path: Path, line: str) -> None:
    """Directly append a line to a file (bypasses EventWriter's redaction)."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def test_redact_preserves_original_journal_as_backup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)
    sd = tmp_path / ".ro-crate-run"
    # Inject a raw secret directly into a log file (simulating an old unredacted capture)
    (sd / "logs").mkdir(exist_ok=True)
    (sd / "logs" / "leaked.txt").write_text(
        "API_KEY=abcd1234supersecretvalue\n", encoding="utf-8"
    )
    rc = redact_run(sd, apply=True)
    assert rc == 0
    backups = list(sd.glob("events.ndjson.pre-redaction-*"))
    assert backups, "original journal must be preserved as backup"
    assert "abcd1234supersecretvalue" not in (sd / "logs" / "leaked.txt").read_text()
    types = [e["event_type"] for e in read_events(sd)]
    assert "redaction.applied" in types


def test_append_fails_closed_when_redaction_errors(tmp_path: Path, monkeypatch) -> None:
    # A broken redaction policy must NOT cause the original (secret-bearing) payload to be
    # persisted: EventWriter fails closed — content dropped, event flagged redacted.
    import json

    from ro_crate_run.journal import EventWriter

    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)
    sd = tmp_path / ".ro-crate-run"

    import ro_crate_run.redaction as redaction_mod

    def _boom(*a, **k):  # type: ignore[no-untyped-def]
        raise ValueError("invalid custom redaction regex")

    monkeypatch.setattr(redaction_mod.Redactor, "from_config", staticmethod(_boom))
    EventWriter(sd).append("human.note", {"text": "API_KEY=supersecretvalue"},
                           source_kind="human_cli")

    journal_text = (sd / "events.ndjson").read_text()
    assert "supersecretvalue" not in journal_text, "secret persisted despite redaction failure"
    note = [e for e in read_events(sd) if e["event_type"] == "human.note"][-1]
    assert note["redacted"] is True
    assert note["payload"].get("redaction_error") is True
    assert "supersecretvalue" not in json.dumps(note["payload"])


def test_redact_emits_redaction_failed_on_error(tmp_path: Path, monkeypatch) -> None:
    """If _redact_event_journal raises, redaction.failed is emitted."""
    import ro_crate_run.redact as redact_mod

    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)
    sd = tmp_path / ".ro-crate-run"
    # Inject a raw secret into a log so findings exist
    (sd / "logs").mkdir(exist_ok=True)
    (sd / "logs" / "leak.txt").write_text("API_KEY=badval12345supersecretval\n")

    def _boom(state_dir: Path, redactor: object) -> None:
        raise RuntimeError("simulated journal error")

    monkeypatch.setattr(redact_mod, "_redact_event_journal", _boom)

    with pytest.raises(RuntimeError):
        redact_run(sd, apply=True)

    # redaction.failed should be in the journal
    types = [e["event_type"] for e in read_events(sd)]
    assert "redaction.failed" in types
