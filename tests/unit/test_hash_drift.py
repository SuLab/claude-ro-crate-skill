from __future__ import annotations

from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.validation.validator import validate_run


def test_validate_detects_post_checkpoint_hash_drift(
    tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    """`rcr validate` must flag a declared output whose on-disk bytes drifted after checkpoint.

    Scenario: start a run, produce + declare an output via `rcr run`, checkpoint (which
    records the output's sha256), then tamper with the file's bytes on disk. A subsequent
    validation must surface a `file_content_mismatch` finding for that path.
    """
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Hash drift demo", "--no-checkpoint"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "result.txt",
                "--",
                "sh",
                "-c",
                "printf 'original payload\\n' > result.txt",
            ]
        )
        == 0
    )
    produced = tmp_path / "result.txt"
    assert produced.read_text() == "original payload\n"
    assert main(["checkpoint"]) == 0

    # Tamper with the declared output AFTER its sha256 was recorded at checkpoint.
    produced.write_text("TAMPERED after checkpoint\n")

    state_dir = tmp_path / ".ro-crate-run"
    report = validate_run(state_dir, strict=False, public=False, append_event=False)

    mismatches = [f for f in report.errors if f.code == "file_content_mismatch"]
    assert mismatches, "validation must detect result.txt no longer matches recorded sha256"
    assert any(f.path == "result.txt" for f in mismatches)
