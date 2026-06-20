from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ro_crate_run.config import default_config
from ro_crate_run.models import PrivacyFinding
from ro_crate_run.redaction import Redactor
from ro_crate_run.validation.privacy import (
    check_privacy,
    check_public_export_payload,
    env_findings,
    journal_findings,
    log_findings,
    public_export_findings,
    scan_crate_secrets,
    source_diff_findings,
)


def test_public_export_fails_on_raw_prompt() -> None:
    findings = check_public_export_payload(
        {"human_prompt": "please analyze private data"},
        include_prompts=False,
    )
    assert PrivacyFinding("error", "raw_prompt_in_public_export") in findings


def test_public_export_fails_on_secret_pattern() -> None:
    findings = check_public_export_payload(
        {"log": "token ghp_abcdefghijklmnopqrstuvwxyz1234567890"},
        include_prompts=True,
    )
    assert any(f.code == "secret_pattern" for f in findings)


# --- scan_crate_secrets ---


def test_scan_crate_secrets_flags_planted_key(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run").mkdir(parents=True)
    (crate / ".ro-crate-run" / "events.ndjson").write_text("AKIAIOSFODNN7EXAMPLE\n")
    findings = scan_crate_secrets(crate, Redactor.default())
    assert any(f.code == "secret_pattern" for f in findings)


def test_scan_crate_secrets_clean(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    crate.mkdir()
    (crate / "out.txt").write_text("just ordinary output\n")
    assert scan_crate_secrets(crate, Redactor.default()) == []


def test_scan_crate_secrets_does_not_fail_open_on_binary(tmp_path: Path) -> None:
    # A secret embedded in an otherwise-binary (non-UTF-8) file must still be flagged — the
    # scanner must not skip the file on UnicodeDecodeError (that would fail the gate open).
    crate = tmp_path / "crate"
    crate.mkdir()
    blob = b"\x00\x01\xff\xfe binary noise " + b"AKIAIOSFODNN7EXAMPLE" + b"\x80\x81\x00"
    (crate / "model.bin").write_bytes(blob)
    findings = scan_crate_secrets(crate, Redactor.default())
    assert any(f.code == "secret_pattern" for f in findings), \
        "secret in a binary file was not detected (gate failed open)"


# --- journal_findings ---


def _write_journal(crate: Path, *events: dict) -> None:  # type: ignore[type-arg]
    j = crate / ".ro-crate-run" / "events.ndjson"
    j.parent.mkdir(parents=True, exist_ok=True)
    j.write_text("".join(json.dumps(e) + "\n" for e in events))


def test_journal_findings_flags_journal_without_include(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    _write_journal(crate, {"event_type": "run.started", "payload": {}})
    findings = journal_findings(crate, include_event_journal=False, include_prompts=True)
    assert any(f.code == "event_journal_in_public_export" for f in findings)


def test_journal_findings_flags_prompt_without_include(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    _write_journal(crate, {"event_type": "human.prompt", "payload": {"prompt": "use my token"}})
    findings = journal_findings(crate, include_event_journal=True, include_prompts=False)
    assert any(f.code == "raw_prompt_in_public_export" for f in findings)


def test_journal_findings_clean_when_explicitly_allowed(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    _write_journal(crate, {"event_type": "human.prompt", "payload": {"prompt": "x"}})
    findings = journal_findings(crate, include_event_journal=True, include_prompts=True)
    assert findings == []


# --- source_diff_findings ---


def test_source_diff_findings_flags_source(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / "src").mkdir(parents=True)
    (crate / "src" / "lib.py").write_text("print('x')\n")
    findings = source_diff_findings(
        crate,
        source_roots=["src", "scripts"],
        include_source_code_public=False,
        include_git_diff_public=False,
    )
    assert any(f.code == "source_code_in_public_export" for f in findings)


def test_source_diff_findings_allows_source_when_enabled(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / "src").mkdir(parents=True)
    (crate / "src" / "lib.py").write_text("print('x')\n")
    findings = source_diff_findings(
        crate,
        source_roots=["src"],
        include_source_code_public=True,
        include_git_diff_public=False,
    )
    assert all(f.code != "source_code_in_public_export" for f in findings)


def test_source_diff_findings_flags_diff(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    crate.mkdir()
    (crate / "changes.diff").write_text("--- a\n+++ b\n")
    findings = source_diff_findings(
        crate,
        source_roots=["src"],
        include_source_code_public=True,
        include_git_diff_public=False,
    )
    assert any(f.code == "git_diff_in_public_export" for f in findings)


# --- env_findings ---


def test_env_findings_flags_outside_allowlist(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run" / "commands").mkdir(parents=True)
    (crate / ".ro-crate-run" / "commands" / "cmd_000001.json").write_text(
        json.dumps({"environment": {"PATH": "/bin", "MY_SECRET_ENV": "x"}})
    )
    findings = env_findings(crate, allowlist=["PATH"])
    codes = {f.code for f in findings}
    assert "env_var_outside_allowlist" in codes
    assert all("MY_SECRET_ENV" in f.path for f in findings)


def test_env_findings_clean_when_all_allowlisted(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run" / "commands").mkdir(parents=True)
    (crate / ".ro-crate-run" / "commands" / "cmd_000001.json").write_text(
        json.dumps({"environment": {"PATH": "/bin"}})
    )
    assert env_findings(crate, allowlist=["PATH"]) == []


# --- log_findings ---


def test_log_findings_flags_oversized(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run" / "logs").mkdir(parents=True)
    (crate / ".ro-crate-run" / "logs" / "big.stdout.txt").write_text("x" * (2 * 1024 * 1024))
    findings = log_findings(crate, include_full_logs=False, max_log_size_mb=1)
    assert any(f.code == "full_log_in_public_export" for f in findings)


def test_log_findings_skipped_when_full_logs_allowed(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run" / "logs").mkdir(parents=True)
    (crate / ".ro-crate-run" / "logs" / "big.stdout.txt").write_text("x" * (2 * 1024 * 1024))
    assert log_findings(crate, include_full_logs=True, max_log_size_mb=1) == []


# --- public_export_findings + check_privacy ---


@dataclass
class _Ctx:
    crate_dir: Path | None
    cfg: Any
    public: bool
    metadata: Any = None
    state_dir: Path = Path(".")


def test_public_export_findings_aggregates(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run").mkdir(parents=True)
    (crate / ".ro-crate-run" / "events.ndjson").write_text(
        json.dumps({"event_type": "human.prompt", "payload": {"prompt": "x"}}) + "\n"
    )
    ctx = _Ctx(crate_dir=crate, cfg=default_config("p"), public=True)
    codes = {f.code for f in public_export_findings(ctx)}  # type: ignore[arg-type]
    assert "event_journal_in_public_export" in codes
    assert "raw_prompt_in_public_export" in codes


def test_public_export_findings_loads_custom_policy_relative_to_state_dir(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "project"
    state_dir = project / ".ro-crate-run"
    crate = state_dir / "ro-crate"
    crate.mkdir(parents=True)
    (state_dir / "secrets-redaction.json").write_text(
        json.dumps({"patterns": [r"PROJECTSECRET-[0-9]{4}"]})
    )
    (crate / "ro-crate-metadata.json").write_text("PROJECTSECRET-2222\n")
    cfg = default_config("p")
    cfg.redaction.patterns_file = ".ro-crate-run/secrets-redaction.json"
    monkeypatch.chdir(tmp_path)

    ctx = _Ctx(crate_dir=crate, cfg=cfg, public=True, state_dir=state_dir)
    codes = {f.code for f in public_export_findings(ctx)}  # type: ignore[arg-type]

    assert "secret_pattern" in codes


def test_check_privacy_skips_when_not_public(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    crate.mkdir()
    ctx = _Ctx(crate_dir=crate, cfg=default_config("p"), public=False)
    assert check_privacy(ctx) == []  # type: ignore[arg-type]


def test_check_privacy_skips_when_gate_disabled(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    (crate / ".ro-crate-run").mkdir(parents=True)
    (crate / ".ro-crate-run" / "events.ndjson").write_text("AKIAIOSFODNN7EXAMPLE\n")
    cfg = default_config("p")
    cfg.validation.require_privacy_gate = False
    ctx = _Ctx(crate_dir=crate, cfg=cfg, public=True)
    assert check_privacy(ctx) == []  # type: ignore[arg-type]
