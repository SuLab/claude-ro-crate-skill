import json
from pathlib import Path

from ro_crate_run import commands
from ro_crate_run.config import default_config
from ro_crate_run.models import RedactionResult
from ro_crate_run.redact import redact_run
from ro_crate_run.redaction import Redactor, redaction_event_payload


def test_redaction_event_payload_omits_text() -> None:
    r = Redactor.default()
    result = r.redact_text("token API_KEY=supersecretvalue123")
    payload = redaction_event_payload("note", result)
    assert payload == {"context": "note", "applied": result.applied, "categories": list(result.categories)}
    assert "supersecretvalue123" not in json.dumps(payload)
    assert "text" not in payload


def test_extra_applied_adds_count_only_total_without_categories() -> None:
    # The count-only seam: an integer tally (e.g. sidecar/stream pumps) bumps
    # `applied` but never `categories`, and yields the same payload the old
    # category-less RedactionResult("", n, ()) placeholder produced.
    r = Redactor.default()
    result = r.redact_text("token API_KEY=supersecretvalue123")
    seam = redaction_event_payload("note", result, extra_applied=2)
    placeholder = redaction_event_payload("note", result, RedactionResult("", 2, ()))
    assert seam == placeholder
    assert seam["applied"] == result.applied + 2
    assert seam["categories"] == list(result.categories)


def test_extra_applied_alone_carries_no_categories() -> None:
    payload = redaction_event_payload("execution.command", extra_applied=3)
    assert payload == {"context": "execution.command", "applied": 3, "categories": []}


def test_redact_run_uses_policy_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)
    sd = tmp_path / ".ro-crate-run"
    (tmp_path / "policy.json").write_text('{"patterns": ["ZZTOPSECRET"]}')
    (sd / "logs").mkdir(exist_ok=True)
    (sd / "logs" / "x.txt").write_text("see ZZTOPSECRET now")
    rc = redact_run(sd, apply=True, policy=str(tmp_path / "policy.json"))
    assert rc == 0
    assert "ZZTOPSECRET" not in (sd / "logs" / "x.txt").read_text()


def test_from_config_loads_custom_patterns(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    state_dir.mkdir()
    (state_dir / "secrets-redaction.json").write_text(
        json.dumps({"patterns": [r"CUSTOMSECRET-[0-9]{4}"]})
    )
    cfg = default_config(project_name="p", mode="monitored", profile="process")
    cfg.redaction.patterns_file = ".ro-crate-run/secrets-redaction.json"
    r = Redactor.from_config(cfg, state_dir=state_dir)
    out = r.redact_text("token CUSTOMSECRET-1234 here")
    assert out.applied >= 1
    assert "CUSTOMSECRET-1234" not in out.text


def test_redacts_jwt_bearer_and_cloud_keys() -> None:
    r = Redactor.default()
    samples = [
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dQw4w9WgXcQabcdEFG_hiJKlmno",
        "Authorization: Bearer abcDEF1234567890abcDEF1234567890",
        "key=AIzaSyA1234567890abcdefghijklmnopqrstuv",
    ]
    for s in samples:
        out = r.redact_text(s)
        assert out.applied >= 1, s
        assert "[REDACTED:secret]" in out.text, s


def test_secret_like_values_are_redacted() -> None:
    redactor = Redactor.default()
    text = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456"
    result = redactor.redact_text(text)
    assert "sk-" not in result.text
    assert "[REDACTED:secret]" in result.text


def test_environment_capture_is_allowlist_based() -> None:
    redactor = Redactor.default(environment_allowlist=["PATH", "LANG"])
    env = {"PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": "abc", "LANG": "C.UTF-8"}
    captured = redactor.capture_environment(env)
    assert captured == {"PATH": "/usr/bin", "LANG": "C.UTF-8"}


def test_environment_capture_redacts_allowlisted_values(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ro-crate-run"
    state_dir.mkdir()
    (state_dir / "secrets-redaction.json").write_text(
        json.dumps({"patterns": [r"PROJECTSECRET-[0-9]{4}"]})
    )
    cfg = default_config(project_name="p", mode="monitored", profile="process")
    cfg.redaction.environment_allowlist = ["SAFE_PATH"]
    redactor = Redactor.from_config(cfg, state_dir=state_dir)

    captured = redactor.capture_environment({"SAFE_PATH": "PROJECTSECRET-7777"})

    assert captured == {"SAFE_PATH": "[REDACTED:secret]"}


def test_nested_json_values_are_redacted() -> None:
    value, count = Redactor.default().redact_value(
        {"payload": {"text": "token sk-abcdefghijklmnopqrstuvwxyz123456"}}
    )

    assert count == 1
    assert value["payload"]["text"] == "token [REDACTED:secret]"
