from __future__ import annotations

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
