from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.config import default_config
from ro_crate_run.redaction import (
    Redactor,
    redaction_categories,
    scan_file_for_secrets,
    scan_tree,
)


def test_scan_file_for_secrets_finds_ascii_secret_in_binary_blob(tmp_path: Path) -> None:
    # A file with non-UTF-8 bytes that nonetheless embeds an ASCII secret. The
    # old UTF-8 path skipped this entirely (UnicodeDecodeError); the hardened
    # latin-1 path must still surface it.
    blob = b"\xff\xfe binary preamble " + b"sk-abcdefghijklmnopqrstuvwxyz123456" + b"\x80\x81"
    target = tmp_path / "blob.bin"
    target.write_bytes(blob)
    categories = scan_file_for_secrets(target, Redactor.default())
    assert categories == ["openai-key"]


def test_scan_file_for_secrets_skips_only_unreadable(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert scan_file_for_secrets(missing, Redactor.default()) == []


def test_scan_tree_returns_per_file_categories(tmp_path: Path) -> None:
    (tmp_path / "clean.txt").write_text("nothing here")
    (tmp_path / "leak.txt").write_text("token API_KEY=supersecretvalue1234567")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "key.txt").write_text("A" + "KIA" + "1234567890ABCDEF")
    hits = scan_tree(tmp_path, Redactor.default())
    found = {path.name: cats for path, cats in hits}
    assert "clean.txt" not in found
    assert found["leak.txt"] == ["secret-assignment"]
    assert found["key.txt"] == ["aws-key"]


def test_categories_carry_real_name_with_stable_token() -> None:
    r = Redactor.default()
    result = r.redact_text("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dQw4w9WgXcQabcdEFG_hiJKlmno")
    assert result.categories == ("jwt",)
    assert "[REDACTED:secret]" in result.text


def test_aws_and_bearer_categories() -> None:
    r = Redactor.default()
    assert r.redact_text("A" + "KIA" + "1234567890ABCDEF").categories == ("aws-key",)
    bearer = r.redact_text("Authorization: Bearer abcDEF1234567890abcDEF1234567890")
    assert bearer.categories == ("bearer",)


def test_redaction_categories_unions_results() -> None:
    r = Redactor.default()
    a = r.redact_text("sk-abcdefghijklmnopqrstuvwxyz123456")
    b = r.redact_text("A" + "KIA" + "1234567890ABCDEF")
    assert redaction_categories(a, b) == ["aws-key", "openai-key"]


def test_for_state_dir_resolves_custom_patterns_relative_to_state_dir(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    state_dir.mkdir()
    (state_dir / "secrets-redaction.json").write_text(
        json.dumps({"patterns": [r"CUSTOMSECRET-[0-9]{4}"]})
    )
    cfg = default_config(project_name="p", mode="monitored", profile="process")
    cfg.redaction.patterns_file = ".ro-crate-run/secrets-redaction.json"
    from ro_crate_run.state import write_config

    write_config(state_dir, cfg)
    redactor = Redactor.for_state_dir(state_dir)
    out = redactor.redact_text("token CUSTOMSECRET-1234 here")
    assert out.applied >= 1
    assert "CUSTOMSECRET-1234" not in out.text
    assert "custom" in out.categories


def test_add_patterns_from_appends(tmp_path: Path) -> None:
    redactor = Redactor.default()
    before = len(redactor.patterns)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"patterns": [r"EXTRA-[0-9]{3}"]}))
    redactor.add_patterns_from(policy)
    assert len(redactor.patterns) == before + 1
    out = redactor.redact_text("value EXTRA-123 end")
    assert "EXTRA-123" not in out.text
    assert out.categories == ("custom",)


def test_from_config_disabled_redacts_nothing(tmp_path: Path) -> None:
    cfg = default_config(project_name="p", mode="monitored", profile="process")
    cfg.redaction.enabled = False
    redactor = Redactor.from_config(cfg)
    out = redactor.redact_text("sk-abcdefghijklmnopqrstuvwxyz123456")
    assert out.applied == 0
    assert out.categories == ()
