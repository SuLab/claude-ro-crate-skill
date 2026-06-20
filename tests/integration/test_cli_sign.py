from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.cli import main

pytest.importorskip("cryptography")


def test_sign_after_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Signed", "--profile", "process"]) == 0
    assert main(["sign"]) == 0
    crate = tmp_path / ".ro-crate-run" / "ro-crate"
    assert (crate / "ro-crate-metadata.json.sig").exists()
    # Private key stays out of the crate.
    assert not (crate / "private.pem").exists()
    assert (tmp_path / ".ro-crate-run" / "keys" / "private.pem").exists()


def test_sign_verify_roundtrip_and_tamper_detection(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A signature produced by the real `rcr sign` codepath must verify against the recorded
    # public key, and a post-sign manifest tamper must make `rcr verify` fail.
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Signed", "--profile", "process"]) == 0
    assert main(["sign"]) == 0
    assert main(["verify"]) == 0, "freshly-signed crate must verify"

    manifest = tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json"
    doc = json.loads(manifest.read_text())
    doc["@graph"].append({"@id": "#tamper", "@type": "Thing"})
    manifest.write_text(json.dumps(doc))
    assert main(["verify"]) == 1, "tampered manifest must fail verification"


def test_verify_without_signature_fails_cleanly(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Unsigned", "--profile", "process"]) == 0
    assert main(["verify"]) == 1, "verify with no signature must fail (not crash)"
