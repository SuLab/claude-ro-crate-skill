from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.journal import EventWriter
from ro_crate_run.models import RemoteJournalConfig
from ro_crate_run.remote_journal import mirror_event
from ro_crate_run.state import read_events


def test_file_mirror_appends(tmp_path: Path) -> None:
    target = tmp_path / "remote.ndjson"
    cfg = RemoteJournalConfig(enabled=True, type="file", endpoint=str(target))
    assert mirror_event(cfg, '{"sequence":1}') is True
    assert mirror_event(cfg, '{"sequence":2}') is True
    assert target.read_text().splitlines() == ['{"sequence":1}', '{"sequence":2}']


def test_mirror_reads_type_and_endpoint_directly(tmp_path: Path) -> None:
    # The mirror routes on cfg.type/cfg.endpoint only; the dataclass has no legacy
    # kind/target attributes, so a real RemoteJournalConfig must mirror via them.
    target = tmp_path / "remote.ndjson"
    cfg = RemoteJournalConfig(enabled=True, type="file", endpoint=str(target))
    assert not hasattr(cfg, "kind")
    assert not hasattr(cfg, "target")
    assert mirror_event(cfg, '{"sequence":1}') is True
    assert target.read_text() == '{"sequence":1}\n'


def test_disabled_is_noop(tmp_path: Path) -> None:
    cfg = RemoteJournalConfig(enabled=False, type="file", endpoint=str(tmp_path / "x"))
    assert mirror_event(cfg, "{}") is False


def test_unreachable_file_target_returns_false(tmp_path: Path) -> None:
    # Parent path is a regular file, so the mirror's mkdir fails (OSError) -> degrade to False.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n")
    cfg = RemoteJournalConfig(enabled=True, type="file", endpoint=str(blocker / "x.ndjson"))
    assert mirror_event(cfg, "{}") is False


def test_no_endpoint_returns_false(tmp_path: Path) -> None:
    assert mirror_event(RemoteJournalConfig(enabled=True, type="file", endpoint=None), "{}") is False


def _enable_remote(state_dir: Path, **rj) -> None:  # type: ignore[no-untyped-def]
    cfg_path = state_dir / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["remote_journal"] = {"enabled": True, "type": "file", "endpoint": None,
                             "timeout_seconds": 5, "fail_closed": False, **rj}
    cfg_path.write_text(json.dumps(cfg))


def test_fail_closed_raises_when_mirror_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # With remote_journal.fail_closed set, a mirror failure (here: unreachable target) must
    # raise from the append instead of being silently swallowed.
    monkeypatch.chdir(tmp_path)
    assert main(["start", "RJ", "--no-checkpoint"]) == 0
    sd = tmp_path / ".ro-crate-run"
    blocker = tmp_path / "blocker"
    blocker.write_text("file not dir\n")
    _enable_remote(sd, fail_closed=True, endpoint=str(blocker / "x.ndjson"))
    with pytest.raises(RuntimeError, match="fail_closed"):
        EventWriter(sd).append("human.note", {"text": "x"}, source_kind="human_cli")


def test_fail_open_default_swallows_mirror_failure(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Default (fail_closed=False): a mirror failure must NOT block the local append.
    monkeypatch.chdir(tmp_path)
    assert main(["start", "RJ", "--no-checkpoint"]) == 0
    sd = tmp_path / ".ro-crate-run"
    blocker = tmp_path / "blocker"
    blocker.write_text("file not dir\n")
    _enable_remote(sd, fail_closed=False, endpoint=str(blocker / "x.ndjson"))
    EventWriter(sd).append("human.note", {"text": "ok"}, source_kind="human_cli")  # must not raise
    assert any(e["event_type"] == "human.note" for e in read_events(sd))
