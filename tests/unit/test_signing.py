from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run import signing

cryptography = pytest.importorskip("cryptography")


def test_sign_verify_roundtrip(tmp_path: Path) -> None:
    private_pem, public_pem = signing.generate_keypair()
    manifest = tmp_path / "ro-crate-metadata.json"
    manifest.write_text('{"@graph": []}')
    sig = signing.sign_manifest(manifest, private_pem)
    assert signing.verify_manifest_signature(manifest, sig, public_pem) is True


def test_verify_detects_tamper(tmp_path: Path) -> None:
    private_pem, public_pem = signing.generate_keypair()
    manifest = tmp_path / "ro-crate-metadata.json"
    manifest.write_text('{"@graph": []}')
    sig = signing.sign_manifest(manifest, private_pem)
    manifest.write_text('{"@graph": [{"@id": "tampered"}]}')
    assert signing.verify_manifest_signature(manifest, sig, public_pem) is False


def test_wrong_key_fails(tmp_path: Path) -> None:
    priv1, _ = signing.generate_keypair()
    _, pub2 = signing.generate_keypair()
    manifest = tmp_path / "m.json"
    manifest.write_text("x")
    sig = signing.sign_manifest(manifest, priv1)
    assert signing.verify_manifest_signature(manifest, sig, pub2) is False
