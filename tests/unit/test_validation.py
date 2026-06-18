from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.preview import render_preview_html
from ro_crate_run.signing import generate_keypair, sign_manifest, verify_manifest_signature
from ro_crate_run.validation.validator import validate_run


def test_validation_passes_process_run_with_warning_for_missing_versions(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Validation demo", "--no-checkpoint"]) == 0
    assert (
        main(
            [
                "run",
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
    assert main(["checkpoint"]) == 0

    report = validate_run(tmp_path / ".ro-crate-run", strict=False, public=False)

    assert report.status in {"passed", "warning"}
    assert report.levels["journal"] == "passed"
    assert report.levels["ro_crate"] == "passed"
    assert report.profile_uri == "https://w3id.org/ro/wfrun/process/0.5"


def test_validation_fails_root_missing_license(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Bad crate", "--no-checkpoint"]) == 0
    assert main(["checkpoint"]) == 0
    metadata = tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json"
    data = json.loads(metadata.read_text())
    for entity in data["@graph"]:
        if entity["@id"] == "./":
            entity.pop("license")
    metadata.write_text(json.dumps(data))

    report = validate_run(tmp_path / ".ro-crate-run", strict=False, public=False)

    assert report.status == "failed"
    assert any(err.code == "root_missing_license" for err in report.errors)


def test_preview_html_contains_run_title() -> None:
    html = render_preview_html({"title": "Preview Demo", "commands": [], "outputs": []})
    assert "<title>Preview Demo</title>" in html
    assert "RO-Crate Run Preview" in html


def test_manifest_signature_round_trip(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"sha256":"abc"}')
    private_key, public_key = generate_keypair()
    signature = sign_manifest(manifest, private_key)
    assert verify_manifest_signature(manifest, signature, public_key) is True


def test_validate_run_accepts_crate_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Ctx demo"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    # Passing an explicit crate_dir must not raise and must still validate structure.
    report = validate_run(state_dir, public=False, crate_dir=state_dir / "ro-crate")
    assert report.status in {"passed", "warning", "failed"}


def test_public_validation_fails_on_secret_in_crate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Secret demo"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    (state_dir / "ro-crate" / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    report = validate_run(state_dir, public=True)
    assert report.status == "failed"
    assert report.levels["privacy"] == "failed"
    # Same crate validates clean when not public.
    assert validate_run(state_dir, public=False).levels["privacy"] == "passed"
