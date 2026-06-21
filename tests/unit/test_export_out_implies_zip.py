"""`export --out PATH` must produce the archive even without an explicit --zip.

A caller naming an output path always wants an archive there; passing out=
without zip_output used to be a silent no-op (exit 0, nothing written). out=
now implies zip_output, so the named archive is produced.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.export import finalize


def _start_minimal_run(tmp_path: Path) -> None:
    assert main(["start", "T", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["run", "--", "python3", "-c", "print('x')"]) == 0
    assert main(["checkpoint"]) == 0


def test_finalize_out_without_zip_writes_archive(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _start_minimal_run(tmp_path)

    out = tmp_path / "my-export.zip"
    # zip_output left False on purpose: out= alone must imply a zip request.
    rc = finalize(tmp_path / ".ro-crate-run", zip_output=False, out=out)

    assert rc == 0
    assert out.exists(), "out= without zip_output produced no archive (silent no-op regression)"
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist(), "exported archive is empty"


def test_export_cli_out_without_zip_writes_archive(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _start_minimal_run(tmp_path)

    out = tmp_path / "cli-export.zip"
    # `rcr export --out PATH` with no --zip: the named archive must still appear.
    assert main(["export", "--out", str(out)]) == 0
    assert out.exists(), "rcr export --out without --zip wrote nothing"
