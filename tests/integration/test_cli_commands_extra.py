from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main


def _events(tmp_path: Path) -> list[dict]:
    text = (tmp_path / ".ro-crate-run" / "events.ndjson").read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_input_records_visibility_and_existence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    assert main(["input", "https://example.org/data.csv", "--public"]) == 0
    assert main(["output", "results/report.md", "--required", "--private"]) == 0
    decls = {
        e["payload"]["path"]: e
        for e in _events(tmp_path)
        if e["event_type"].endswith(".declared")
    }
    remote = decls["https://example.org/data.csv"]
    assert remote["visibility"] == "public"
    assert remote["payload"]["existence"] == "observed remote"
    out = decls["results/report.md"]
    assert out["visibility"] == "private"
    assert out["payload"]["existence"] in {"expected", "missing", "declared-only"}


def test_software_emits_lockfile_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    (tmp_path / "requirements.txt").write_text("rocrate\n")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    assert main(["software", "python3"]) == 0
    lock = [e for e in _events(tmp_path) if e["event_type"] == "dependency.lockfile.observed"]
    names = {e["payload"]["path"] for e in lock}
    assert "requirements.txt" in names
    assert "Dockerfile" in names


def test_export_out_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run"]) == 0
    dest = tmp_path / "custom.zip"
    assert main(["export", "--zip", "--out", str(dest)]) == 0
    assert dest.exists()


def test_redact_policy_is_threaded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    policy = tmp_path / "policy.json"
    policy.write_text("{}")
    captured: dict[str, object] = {}
    import ro_crate_run.commands as commands_mod

    original = commands_mod.redact_run

    def spy(state_dir, *, apply=False, policy=None):
        captured["policy"] = policy
        return original(state_dir, apply=apply, policy=policy)

    monkeypatch.setattr(commands_mod, "redact_run", spy)
    assert main(["redact", "--dry-run", "--policy", str(policy)]) == 0
    assert captured["policy"] == policy


def test_step_skipped_distinct_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    assert main(["step", "start", "normalize"]) == 0
    assert main(["step", "end", "normalize", "--status", "skipped"]) == 0
    types = {e["event_type"] for e in _events(tmp_path)}
    assert "workflow.step.skipped" in types
    assert "workflow.step.completed" not in types


def test_config_updates_and_emits_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    assert main(["config", "mode", "enforced"]) == 0
    cfg = json.loads((tmp_path / ".ro-crate-run" / "config.json").read_text())
    assert cfg["mode"] == "enforced"
    assert any(e["event_type"] == "run.config.updated" for e in _events(tmp_path))


def test_abort_emits_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    assert main(["abort", "ran out of time"]) == 0
    aborted = [e for e in _events(tmp_path) if e["event_type"] == "run.aborted"]
    assert aborted and aborted[0]["payload"]["reason"] == "ran out of time"


def test_accept_reject_emit_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0
    assert main(["accept", "results look correct"]) == 0
    assert main(["reject", "rerun with seed 7"]) == 0
    types = {e["event_type"] for e in _events(tmp_path)}
    assert "human.accepted_result" in types
    assert "human.rejected_result" in types
