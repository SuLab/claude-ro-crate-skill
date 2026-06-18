from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run.cli import main
from ro_crate_run.hooks import handle_hook


def test_secret_in_command_output_is_redacted_in_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # a non-allowlisted secret env var must not be captured anywhere
    monkeypatch.setenv("MY_SECRET_TOKEN", "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert main(["start", "Red", "--mode", "monitored", "--profile", "process"]) == 0
    # command prints a secret-shaped value to stdout -> must be redacted in the log
    rc = main(
        ["run", "--", "python3", "-c",
         "print('ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')"]
    )
    assert rc == 0

    state_dir = tmp_path / ".ro-crate-run"
    blob = "\n".join(
        p.read_text(errors="ignore")
        for p in state_dir.rglob("*")
        if p.is_file()
    )
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in blob  # env not captured
    assert "ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in blob  # log redacted


def test_custom_redaction_policy_applies_before_note_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Custom redaction", "--no-checkpoint"]) == 0
    (tmp_path / ".ro-crate-run" / "secrets-redaction.json").write_text(
        '{"patterns": ["PROJECTSECRET-[0-9]{4}"]}'
    )

    assert main(["note", "contains PROJECTSECRET-1234", "--public"]) == 0

    journal = (tmp_path / ".ro-crate-run" / "events.ndjson").read_text()
    assert "PROJECTSECRET-1234" not in journal
    assert "[REDACTED:secret]" in journal


def test_custom_redaction_policy_applies_to_run_logs_before_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Custom log redaction", "--no-checkpoint"]) == 0
    (tmp_path / ".ro-crate-run" / "secrets-redaction.json").write_text(
        '{"patterns": ["PROJECTSECRET-[0-9]{4}"]}'
    )

    assert main(["run", "--", "python3", "-c", "print('PROJECTSECRET-5678')"]) == 0

    blob = "\n".join(
        p.read_text(errors="ignore")
        for p in (tmp_path / ".ro-crate-run").rglob("*")
        if p.is_file()
    )
    assert "PROJECTSECRET-5678" not in blob
    assert "[REDACTED:secret]" in blob


def test_custom_redaction_policy_applies_to_hook_prompt_before_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Custom prompt redaction", "--no-checkpoint"]) == 0
    (tmp_path / ".ro-crate-run" / "secrets-redaction.json").write_text(
        '{"patterns": ["PROJECTSECRET-[0-9]{4}"]}'
    )

    result = handle_hook(
        "UserPromptSubmit",
        {"prompt": "please use PROJECTSECRET-9012"},
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    journal = (tmp_path / ".ro-crate-run" / "events.ndjson").read_text()
    assert "PROJECTSECRET-9012" not in journal
    assert "[REDACTED:secret]" in journal


def test_event_writer_applies_custom_redaction_as_final_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Writer redaction guard", "--no-checkpoint"]) == 0
    (tmp_path / ".ro-crate-run" / "secrets-redaction.json").write_text(
        '{"patterns": ["PROJECTSECRET-[0-9]{4}"]}'
    )

    assert main(["parameter", "threshold", "PROJECTSECRET-3333"]) == 0

    events = [
        json.loads(line)
        for line in (tmp_path / ".ro-crate-run" / "events.ndjson").read_text().splitlines()
    ]
    parameter_event = next(e for e in events if e["event_type"] == "workflow.parameter.declared")
    assert "PROJECTSECRET-3333" not in json.dumps(parameter_event)
    assert parameter_event["payload"]["value"] == "[REDACTED:secret]"
    assert parameter_event["redacted"] is True
