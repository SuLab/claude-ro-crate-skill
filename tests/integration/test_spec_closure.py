import json
import zipfile
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.events import compute_event_hash
from ro_crate_run.hooks import handle_hook
from ro_crate_run.install import install_project
from ro_crate_run.journal import EventWriter
from ro_crate_run.state import load_state, write_state

REQUIRED_HOOKS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Stop",
    "SessionEnd",
}


def _events(state_dir: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (state_dir / "events.ndjson").read_text().splitlines()]


def _metadata(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())


def test_install_project_merges_settings_and_copies_required_hooks(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude/settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))

    assert install_project(str(tmp_path), force=True) == 0

    settings = json.loads(settings_path.read_text())
    assert settings["permissions"] == {"allow": ["Bash(ls)"]}
    assert REQUIRED_HOOKS.issubset(settings["hooks"])
    for hook_name in REQUIRED_HOOKS:
        hook_entries = settings["hooks"][hook_name]
        assert hook_entries
        command = hook_entries[0]["hooks"][0]["command"]
        hook_path = command.replace("${CLAUDE_PROJECT_DIR}", str(tmp_path)).split()[0]
        assert Path(hook_path).exists()
        assert Path(hook_path).stat().st_mode & 0o111
    assert (tmp_path / ".claude/skills/ro-crate-run/SKILL.md").exists()


def test_finalize_public_fails_when_required_output_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Missing output", "--mode", "enforced", "--no-checkpoint"]) == 0
    assert main(["output", "missing.txt", "--role", "report", "--required"]) == 0

    assert main(["finalize", "--public", "--zip"]) == 1

    report = json.loads((tmp_path / ".ro-crate-run/ro-crate/validation-report.json").read_text())
    assert report["status"] == "failed"
    assert any(error["code"] == "missing_required_output" for error in report["errors"])
    assert not list((tmp_path / ".ro-crate-run").glob("*.zip"))


def test_enforced_stop_blocks_open_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Open step", "--mode", "enforced", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["step", "start", "normalize"]) == 0

    result = handle_hook(
        "Stop", {"cwd": str(tmp_path)}, env={"CLAUDE_PROJECT_DIR": str(tmp_path)}
    )

    assert result.exit_code == 2
    assert "open step" in result.stderr


def test_include_event_journal_places_journal_in_private_zip(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Journal export", "--no-checkpoint"]) == 0
    assert main(["note", "Public note", "--public"]) == 0

    assert main(["finalize", "--zip", "--include-event-journal"]) == 0

    [zip_path] = list((tmp_path / ".ro-crate-run").glob("*.zip"))
    with zipfile.ZipFile(zip_path) as archive:
        assert ".ro-crate-run/events.ndjson" in archive.namelist()
    assert (tmp_path / ".ro-crate-run/ro-crate/.ro-crate-run/events.ndjson").exists()


def test_redact_dry_run_reports_findings_and_apply_writes_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / ".ro-crate-run"
    assert main(["start", "Redaction", "--no-checkpoint"]) == 0
    EventWriter(state_dir).append("human.note", {"text": "legacy placeholder"}, source_kind="human_cli")
    events = _events(state_dir)
    events[-1]["payload"] = {"text": "token sk-abcdefghijklmnopqrstuvwxyz123456"}
    events[-1]["redacted"] = False
    events[-1]["event_hash"] = compute_event_hash(events[-1])
    (state_dir / "events.ndjson").write_text(
        "".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events)
    )
    state = load_state(state_dir)
    state.last_event_hash = str(events[-1]["event_hash"])
    write_state(state_dir, state)

    assert main(["redact", "--dry-run"]) == 1
    assert main(["redact", "--apply"]) == 0

    journal_text = (tmp_path / ".ro-crate-run/events.ndjson").read_text()
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in journal_text
    assert "[REDACTED:secret]" in journal_text
    assert "redaction.applied" in journal_text
    assert (tmp_path / ".ro-crate-run/reports/redacted-events.ndjson").exists()


def test_public_notes_decisions_and_parameters_are_materialized(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Public context", "--no-checkpoint"]) == 0
    assert main(["note", "Public analysis note", "--public"]) == 0
    assert main(["decision", "Use threshold", "--rationale", "Protocol", "--public"]) == 0
    assert (
        main(["parameter", "threshold", "0.5", "--formal-parameter", "#param/threshold", "--type", "float"])
        == 0
    )
    assert (
        main(
            [
                "run",
                "--outputs",
                "result.txt",
                "--",
                "python3",
                "-c",
                "open('result.txt','w').write('ok')",
            ]
        )
        == 0
    )

    assert main(["checkpoint"]) == 0

    metadata_text = json.dumps(_metadata(tmp_path))
    assert "Public analysis note" in metadata_text
    assert "Use threshold" in metadata_text
    assert "threshold" in metadata_text
    graph = _metadata(tmp_path)["@graph"]
    assert any(entity.get("@type") == "FormalParameter" for entity in graph)
    assert any(entity.get("@type") == "PropertyValue" for entity in graph)


def test_auto_checkpoint_records_profile_selection_event(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Profile event", "--profile", "auto", "--no-checkpoint"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )

    assert main(["checkpoint", "--profile", "auto"]) == 0

    events = _events(tmp_path / ".ro-crate-run")
    selections = [event for event in events if event["event_type"] == "workflow.profile.selected"]
    assert len(selections) == 1
    assert selections[0]["payload"]["selected_profile"] == "process"
    assert selections[0]["payload"]["profile_uri"] == "https://w3id.org/ro/wfrun/process/0.5"


def test_workflow_run_has_workflow_level_action_instrument(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "workflow.cwl").write_text("class: Workflow\ninputs: []\noutputs: []\nsteps: {}\n")
    assert main(["start", "Workflow action", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["input", "workflow.cwl", "--role", "workflow-definition", "--copy"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )

    assert main(["checkpoint", "--profile", "auto"]) == 0

    graph = _metadata(tmp_path)["@graph"]
    root = next(entity for entity in graph if entity["@id"] == "./")
    workflow_id = root["mainEntity"]["@id"]
    assert any(
        entity.get("@type") == "CreateAction"
        and entity.get("instrument", {}).get("@id") == workflow_id
        for entity in graph
    )


def test_resume_repairs_state_and_reports_current_status(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Resume repair", "--no-checkpoint"]) == 0
    assert main(["note", "one"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    state = load_state(state_dir)
    state.sequence = 0
    state.last_event_hash = None
    write_state(state_dir, state)

    assert main(["resume"]) == 0

    out = capsys.readouterr().out
    repaired = load_state(state_dir)
    assert repaired.sequence >= 3
    assert "Run:" in out
    assert "Profile:" in out
    assert "Last checkpoint:" in out


def test_status_reports_phase_step_checkpoint_and_validation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Status details", "--no-checkpoint"]) == 0
    assert main(["phase", "analysis"]) == 0
    assert main(["step", "start", "s1"]) == 0

    assert main(["status", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["current_phase_id"] == "analysis"
    assert payload["current_step_id"] == "s1"
    assert "last_checkpoint" in payload
    assert "missing_required_metadata" in payload
    assert "privacy_warnings" in payload
    assert "validation" in payload


def test_start_records_runtime_versions_and_os(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["start", "Runtime metadata", "--no-checkpoint"]) == 0

    events = _events(tmp_path / ".ro-crate-run")
    environment = next(event for event in events if event["event_type"] == "environment.observed")
    payload = environment["payload"]
    assert payload["cli_version"] == "0.1.0"
    assert payload["skill_version"] == "0.1.0"
    assert payload["rocrate_package_version"]
    assert payload["os"]


def test_note_and_decision_are_redacted_before_append(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Redacted notes", "--no-checkpoint"]) == 0

    assert main(["note", "token sk-abcdefghijklmnopqrstuvwxyz123456"]) == 0
    assert main(["decision", "Use key sk-abcdefghijklmnopqrstuvwxyz123456"]) == 0

    journal = (tmp_path / ".ro-crate-run/events.ndjson").read_text()
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in journal
    assert "[REDACTED:secret]" in journal


def test_software_command_attempts_version_and_path_capture(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Software metadata", "--no-checkpoint"]) == 0

    assert main(["software", "python3"]) == 0

    events = _events(tmp_path / ".ro-crate-run")
    software = [event for event in events if event["event_type"] == "software.observed"][-1]
    payload = software["payload"]
    assert payload["version"] != "unknown"
    assert payload["executable_path"]
