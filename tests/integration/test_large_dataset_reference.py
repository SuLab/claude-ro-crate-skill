from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.cli import main


def test_large_input_is_referenced_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Big", "--mode", "monitored", "--profile", "process"]) == 0
    # config file_policy.max_file_size_mb controls copy vs reference for size;
    # set to 0 so any file is "too large" to copy
    cfg_path = tmp_path / ".ro-crate-run" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["file_policy"]["max_file_size_mb"] = 0  # everything is "too large" to copy
    cfg_path.write_text(json.dumps(cfg, indent=2))
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 4096)
    assert main(["input", "big.bin", "--role", "dataset", "--required"]) == 0
    assert main(["checkpoint", "--profile", "process"]) in {0, 1}

    crate_dir = tmp_path / ".ro-crate-run" / "ro-crate"
    # entity exists by reference, but the bytes are NOT copied into the crate
    assert not (crate_dir / "big.bin").exists()
    meta = json.loads((crate_dir / "ro-crate-metadata.json").read_text())
    ids = {e.get("@id") for e in meta["@graph"]}
    assert "big.bin" in ids
