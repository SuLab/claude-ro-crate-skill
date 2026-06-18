"""Sensitive files (.env, *.pem, ...) are never read, hashed, or copied (SPEC §13.1)."""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main


def test_sensitive_file_never_captured(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "secret.env").write_text("API_KEY=topsecretvalue123\n")
    assert main(["start", "T", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    # Even with inputs configured to be copied, a sensitive file must not be captured.
    assert main(["config", "file_policy.include_declared_inputs", "true"]) == 0
    assert main(["input", "secret.env", "--role", "config", "--copy"]) == 0
    assert main(["run", "--", "python3", "-c", "print('x')"]) == 0
    assert main(["checkpoint"]) == 0

    crate_dir = tmp_path / ".ro-crate-run" / "ro-crate"
    for p in crate_dir.rglob("*"):
        if p.is_file():
            assert "topsecretvalue123" not in p.read_text(errors="ignore"), f"secret leaked into {p}"
    assert not (crate_dir / "secret.env").exists(), "sensitive file was copied into the crate"
    meta = json.loads((crate_dir / "ro-crate-metadata.json").read_text())
    ent = [e for e in meta["@graph"] if e.get("@id") == "secret.env"]
    assert ent, "no File entity for the declared sensitive input"
    assert "identifier" not in ent[0], "sensitive file was hashed (sha256 recorded)"
