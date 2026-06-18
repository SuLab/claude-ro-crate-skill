from __future__ import annotations

from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.validation.context import build_context
from ro_crate_run.validation.rocrate import check_rocrate
from ro_crate_run.validation.validator import validate_run


def _run_with_declared_output(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Integrity demo", "--no-checkpoint"]) == 0
    (tmp_path / "result.txt").write_text("original payload\n")
    assert main(["output", "result.txt"]) == 0
    assert main(["checkpoint"]) == 0
    return tmp_path / ".ro-crate-run"


def test_clean_crate_has_no_content_mismatch(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _run_with_declared_output(tmp_path, monkeypatch)
    findings = check_rocrate(build_context(state_dir, strict=False, public=False))
    assert not any(f.code == "file_content_mismatch" for f in findings)


def test_check_rocrate_detects_declared_file_content_drift(
    tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    state_dir = _run_with_declared_output(tmp_path, monkeypatch)
    # Modify the declared output on disk AFTER checkpoint recorded its sha256.
    (tmp_path / "result.txt").write_text("TAMPERED after checkpoint\n")
    findings = check_rocrate(build_context(state_dir, strict=False, public=False))
    mismatches = [f for f in findings if f.code == "file_content_mismatch"]
    assert mismatches, "validation must detect result.txt no longer matches recorded sha256"
    assert mismatches[0].path == "result.txt"


def test_validate_run_fails_on_file_content_drift(
    tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    state_dir = _run_with_declared_output(tmp_path, monkeypatch)
    (tmp_path / "result.txt").write_text("TAMPERED after checkpoint\n")
    report = validate_run(state_dir, strict=False, public=False, append_event=False)
    assert report.status == "failed"
    assert any(f.code == "file_content_mismatch" for f in report.errors)
