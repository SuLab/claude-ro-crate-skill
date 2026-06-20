from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ro_crate_run.config import default_config
from ro_crate_run.redaction import Redactor
from ro_crate_run.validation.privacy import check_public_export_payload, public_export_findings


@dataclass
class _Ctx:
    crate_dir: Path | None
    cfg: Any
    public: bool
    metadata: Any = None
    state_dir: Path = Path(".")


def test_payload_scan_defaults_to_builtin_patterns() -> None:
    # Without an explicit redactor the payload scan still catches built-in secret patterns.
    findings = check_public_export_payload(
        {"log": "ghp_abcdefghijklmnopqrstuvwxyz1234567890"}, include_prompts=True
    )
    assert any(f.code == "secret_pattern" for f in findings)


def test_payload_scan_honors_custom_redactor_patterns() -> None:
    # A value matching only a user's custom pattern must be caught when that
    # redactor is threaded in — the built-in set alone would miss it.
    import re

    payload = {"note": "PROJECTSECRET-4242"}

    # Built-in redactor does not know the custom pattern.
    assert check_public_export_payload(payload, include_prompts=True) == []

    # A redactor carrying the custom pattern flags it.
    custom = Redactor.default()
    custom.patterns = [*custom.patterns, ("custom", re.compile(r"PROJECTSECRET-[0-9]{4}"))]
    findings = check_public_export_payload(payload, include_prompts=True, redactor=custom)
    assert any(f.code == "secret_pattern" for f in findings)


def test_metadata_scan_uses_config_custom_patterns(tmp_path: Path) -> None:
    # End-to-end: the L5 gate's in-memory metadata scan must honor the user's
    # custom patterns_file exactly as the on-disk file scan does (no asymmetry).
    project = tmp_path / "project"
    state_dir = project / ".ro-crate-run"
    crate = state_dir / "ro-crate"
    crate.mkdir(parents=True)
    (state_dir / "secrets-redaction.json").write_text(
        json.dumps({"patterns": [r"CUSTOMTOKEN-[0-9]{4}"]})
    )
    # A clean on-disk crate, but the projected metadata carries the custom secret.
    (crate / "ro-crate-metadata.json").write_text("{}\n")

    cfg = default_config("p")
    cfg.redaction.patterns_file = ".ro-crate-run/secrets-redaction.json"

    ctx = _Ctx(
        crate_dir=crate,
        cfg=cfg,
        public=True,
        state_dir=state_dir,
        metadata={"@graph": [{"description": "CUSTOMTOKEN-9999"}]},
    )
    codes = {f.code for f in public_export_findings(ctx)}  # type: ignore[arg-type]
    assert "secret_pattern" in codes
