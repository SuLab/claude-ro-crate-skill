"""Regression tests for gaps found by the independent SPEC-vs-code re-audit."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ro_crate_run import hooks
from ro_crate_run.cli import main
from ro_crate_run.models import ValidationFinding, ValidationReport
from ro_crate_run.state import load_state, update_state


def test_start_in_git_repo_without_commit_or_remote(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """E1: a fresh `git init` (no commit, no remote) must not crash `rcr start`.

    git fields are omitted rather than serialized as JSON null (which the event
    writer rejects)."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["start", "fresh", "--no-checkpoint"]) == 0
    events = [
        json.loads(line)
        for line in (tmp_path / ".ro-crate-run" / "events.ndjson").read_text().splitlines()
    ]
    env = next(e for e in events if e["event_type"] == "environment.observed")
    git = env["payload"]["git"]
    assert git["available"] is True
    assert "commit" not in git and "remote" not in git  # omitted, never null


def test_monitored_stop_blocks_when_checkpoint_raises(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """E3: if checkpoint raises (e.g. an unrecoverable journal), the monitored Stop
    hook blocks with actionable stderr instead of crashing the hook process."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["start", "m", "--mode", "monitored", "--no-checkpoint"]) == 0
    monkeypatch.setattr(hooks, "_is_stale", lambda state: True)
    import ro_crate_run.materialize.builder as builder

    def _boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("simulated corrupt journal")

    monkeypatch.setattr(builder, "checkpoint", _boom)
    result = hooks.handle_hook("Stop", {"cwd": str(tmp_path)}, env={})
    assert result.exit_code == 2
    assert "checkpoint failed" in result.stderr.lower()


def test_stop_blockers_blocks_structural_errors_in_monitored(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """E2: structural (journal/state/ro_crate) validation errors block in monitored
    mode too (SPEC §10.4: invalid JSON-LD / corrupt journal are critical failures)."""
    monkeypatch.chdir(tmp_path)
    assert main(["start", "m", "--no-checkpoint"]) == 0
    state = load_state(tmp_path / ".ro-crate-run")
    report = ValidationReport(
        "failed",
        "process",
        "https://w3id.org/ro/wfrun/process/0.5",
        {},
        [ValidationFinding("ro_crate", "jsonld_expansion_failed", "JSON-LD failed to expand")],
        [],
        [],
    )
    blockers = hooks._stop_blockers(state, report, 0, mode="monitored")
    assert any("JSON-LD" in b for b in blockers)


def test_start_records_claude_session_metadata(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A4 (§9.3): rcr start records Claude Code session metadata in run.started."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-xyz")
    monkeypatch.setenv("CLAUDE_CODE_VERSION", "9.9.9")
    monkeypatch.chdir(tmp_path)
    assert main(["start", "a", "--no-checkpoint"]) == 0
    events = [
        json.loads(line)
        for line in (tmp_path / ".ro-crate-run" / "events.ndjson").read_text().splitlines()
    ]
    run_started = next(e for e in events if e["event_type"] == "run.started")
    assert run_started["payload"]["claude"]["session_id"] == "sess-xyz"
    assert run_started["payload"]["claude"]["version"] == "9.9.9"


def test_output_hash_change_marks_dirty(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A5 (§12.2): a changed output file on disk marks the run dirty at status time."""
    from ro_crate_run.commands import _refresh_run_dirty

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "out.txt").write_text("v1\n")
    assert main(["start", "a", "--no-checkpoint"]) == 0
    assert main(["output", "out.txt", "--role", "result"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    update_state(state_dir, lambda s: setattr(s, "dirty", False))  # isolate the A5 trigger
    (tmp_path / "out.txt").write_text("v2-changed\n")  # mutate the output on disk
    _refresh_run_dirty(state_dir)
    assert load_state(state_dir).dirty is True


def test_checkpoint_aborts_on_tampered_journal(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """C1 (§14.2): checkpoint validates the journal hash chain before building the model."""
    from ro_crate_run.materialize.builder import checkpoint

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["start", "a", "--no-checkpoint"]) == 0
    journal = tmp_path / ".ro-crate-run" / "events.ndjson"
    lines = journal.read_text().splitlines()
    first = json.loads(lines[0])
    first["payload"]["title"] = "TAMPERED"  # content no longer matches stored event_hash
    lines[0] = json.dumps(first)
    journal.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="journal integrity"):
        checkpoint(tmp_path / ".ro-crate-run")


def test_update_state_persists_mutation(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A6 (§11.5): update_state applies and persists a mutation under the run lock."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["start", "a", "--no-checkpoint"]) == 0
    update_state(tmp_path / ".ro-crate-run", lambda s: setattr(s, "title", "renamed"))
    assert load_state(tmp_path / ".ro-crate-run").title == "renamed"
