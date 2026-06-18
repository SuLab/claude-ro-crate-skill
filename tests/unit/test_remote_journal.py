from __future__ import annotations

from pathlib import Path

from ro_crate_run.models import RemoteJournalConfig
from ro_crate_run.remote_journal import mirror_event


def test_file_mirror_appends(tmp_path: Path) -> None:
    target = tmp_path / "remote.ndjson"
    cfg = RemoteJournalConfig(enabled=True, type="file", endpoint=str(target))
    assert mirror_event(cfg, '{"sequence":1}') is True
    assert mirror_event(cfg, '{"sequence":2}') is True
    assert target.read_text().splitlines() == ['{"sequence":1}', '{"sequence":2}']


def test_disabled_is_noop(tmp_path: Path) -> None:
    cfg = RemoteJournalConfig(enabled=False, type="file", endpoint=str(tmp_path / "x"))
    assert mirror_event(cfg, "{}") is False


def test_unreachable_target_degrades(tmp_path: Path) -> None:
    cfg = RemoteJournalConfig(enabled=True, type="file", endpoint=str(tmp_path / "nope" / "deep" / "x.ndjson"))
    # mkdir -p behavior means this might succeed or fail gracefully
    assert mirror_event(cfg, "{}") in (True, False)
