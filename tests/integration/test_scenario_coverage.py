from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.state import read_events


def test_resume_reports_and_appends_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # SPEC 21.2 #2
    monkeypatch.chdir(tmp_path)
    assert main(["start", "R", "--mode", "monitored", "--profile", "process"]) == 0
    assert main(["resume"]) == 0
    types = [e["event_type"] for e in read_events(tmp_path / ".ro-crate-run")]
    assert "run.resumed" in types


def test_finalize_zip_produces_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # SPEC 21.2 #12
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Z", "--mode", "monitored", "--profile", "process"]) == 0
    assert main(["output", "out.txt", "--required"]) == 0
    assert (
        main(["run", "--outputs", "out.txt", "--",
              "python3", "-c", "open('out.txt','w').write('ok')"]) == 0
    )
    assert main(["finalize", "--zip"]) == 0
    archives = list((tmp_path / ".ro-crate-run").rglob("*.zip"))
    assert archives, "no zip archive produced by finalize --zip"
    with zipfile.ZipFile(archives[0]) as zf:
        assert any(n.endswith("ro-crate-metadata.json") for n in zf.namelist())


def test_public_finalize_excludes_event_journal_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # SPEC 21.2 #11
    monkeypatch.chdir(tmp_path)
    assert main(["start", "P", "--mode", "monitored", "--profile", "process"]) == 0
    assert main(["output", "out.txt", "--required"]) == 0
    assert (
        main(["run", "--outputs", "out.txt", "--",
              "python3", "-c", "open('out.txt','w').write('ok')"]) == 0
    )
    assert main(["finalize", "--public"]) == 0
    crate = tmp_path / ".ro-crate-run" / "ro-crate"
    assert not list(crate.rglob("events.ndjson")), (
        "public finalize should not include events.ndjson"
    )
