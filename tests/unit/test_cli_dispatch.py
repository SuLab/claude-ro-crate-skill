from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run import commands
from ro_crate_run.cli import _tri_state, main


def test_tri_state_resolution() -> None:
    assert _tri_state(True, False) is True
    assert _tri_state(False, True) is False
    assert _tri_state(False, False) is None


def test_every_subparser_binds_a_func(monkeypatch: pytest.MonkeyPatch) -> None:
    # Dispatch goes through args.func; assert each declared subcommand sets one so a
    # parser/dispatch drift can't silently misroute.
    import argparse

    recorded: list[str] = []

    def _capture(self: argparse.ArgumentParser, *args: object, **kwargs: object) -> object:
        if "func" in kwargs:
            recorded.append("func")
        return _orig(self, *args, **kwargs)

    _orig = argparse.ArgumentParser.set_defaults
    monkeypatch.setattr(argparse.ArgumentParser, "set_defaults", _capture)
    with pytest.raises(SystemExit):
        main(["--help"])
    # At least every top-level command registered a func.
    assert recorded.count("func") >= 20


def test_validate_public_flag_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def _fake(strict: bool = False, json_output: bool = False, public: bool = False) -> int:
        captured["strict"] = strict
        captured["json"] = json_output
        captured["public"] = public
        return 0

    monkeypatch.setattr(commands, "do_validate", _fake)
    assert main(["start", "demo", "--no-checkpoint"]) == 0
    assert main(["validate", "--public", "--strict"]) == 0
    assert captured == {"strict": True, "json": False, "public": True}


def test_export_never_emits_public(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def _fake_finalize(
        zip_output: bool,
        public: bool | None,
        include_event_journal: bool,
        out: str | None = None,
        sign: bool = False,
    ) -> int:
        captured["public"] = public
        captured["include_event_journal"] = include_event_journal
        captured["out"] = out
        captured["zip"] = zip_output
        return 0

    monkeypatch.setattr(commands, "do_finalize", _fake_finalize)
    assert main(["start", "demo", "--no-checkpoint"]) == 0
    assert main(["export", "--zip", "--out", "x.zip"]) == 0
    assert captured["public"] is False
    assert captured["include_event_journal"] is False
    assert captured["out"] == "x.zip"
    assert captured["zip"] is True


def test_inspect_events_prints_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "demo", "--no-checkpoint"]) == 0
    assert main(["inspect", "--events"]) == 0
    out = capsys.readouterr().out
    # Parses as JSON (not a Python dict repr) and carries the expected keys.
    parsed = json.loads(out)
    assert "event_count" in parsed
    assert "event_types" in parsed


def _events(state_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (state_dir / "events.ndjson").read_text().splitlines()
        if line.strip()
    ]


def test_record_result_emits_redaction_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An accepted result that contained a secret must emit a redaction.applied audit
    # follow-up, mirroring note()/decision().
    monkeypatch.chdir(tmp_path)
    assert main(["start", "demo", "--no-checkpoint"]) == 0
    assert main(["accept", "ship it with token=AKIAIOSFODNN7EXAMPLE"]) == 0
    events = _events(tmp_path / ".ro-crate-run")
    applied = [e for e in events if e["event_type"] == "redaction.applied"]
    assert applied
    assert applied[-1]["payload"]["context"] == "human.accepted_result"
    assert applied[-1]["payload"]["applied"] >= 1


def test_decision_redaction_applied_preserves_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # decision() must union categories across text + rationale, not drop them to [].
    monkeypatch.chdir(tmp_path)
    assert main(["start", "demo", "--no-checkpoint"]) == 0
    assert (
        main(["decision", "use token=AKIAIOSFODNN7EXAMPLE", "--rationale", "fine"]) == 0
    )
    events = _events(tmp_path / ".ro-crate-run")
    applied = [e for e in events if e["event_type"] == "redaction.applied"]
    assert applied
    assert applied[-1]["payload"]["context"] == "human.decision"
    assert applied[-1]["payload"]["categories"]  # non-empty, not the old []
