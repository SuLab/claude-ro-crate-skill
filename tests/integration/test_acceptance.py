from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.validation.validator import validate_run


def test_acceptance_full_process_public_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "start",
                "Acceptance",
                "--mode",
                "monitored",
                "--profile",
                "process",
                "--no-checkpoint",
            ]
        )
        == 0
    )
    (tmp_path / "input.txt").write_text("input\n")
    assert main(["input", "input.txt", "--role", "dataset", "--required"]) == 0
    assert main(["parameter", "threshold", "0.5", "--type", "float"]) == 0
    assert main(["software", "python3", "--type", "SoftwareApplication"]) == 0
    assert main(["phase", "analysis"]) == 0
    assert (
        main(
            [
                "run",
                "--inputs",
                "input.txt",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )
    assert main(["phase", "complete", "analysis"]) == 0
    assert main(["finalize", "--zip", "--public"]) == 0
    report = validate_run(tmp_path / ".ro-crate-run", strict=False, public=True)
    assert report.status in {"passed", "warning"}
    assert (tmp_path / ".ro-crate-run/reports/final-summary.json").exists()
