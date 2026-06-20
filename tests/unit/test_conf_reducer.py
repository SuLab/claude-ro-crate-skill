from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.materialize.run_model import build_run_model
from ro_crate_run.models import RunModel


def _seed_run(tmp_path: Path) -> Path:
    """Create a minimal valid .ro-crate-run journal with the required header events.

    Uses the real `rcr start` via the package CLI in the tmp project dir so the journal
    header (run.created etc.) matches production exactly.
    """
    import subprocess
    import sys

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=x",
         "commit", "--allow-empty", "-qm", "init"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(
        [sys.executable, "-c",
         "import sys; from ro_crate_run.cli import main; sys.exit(main())",
         "start", "ConfReducer", "--profile", "process", "--no-checkpoint"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path / ".ro-crate-run"


def _append_post_tool(state_dir: Path, payload: dict[str, object]) -> None:
    """Append a tool.completed event exactly as the PostToolUse hook would."""
    from ro_crate_run.hooks import handle_hook

    handle_hook("PostToolUse", payload, env={"CLAUDE_PROJECT_DIR": str(state_dir.parent)})


def _ask_payload(cwd: str) -> dict[str, object]:
    return {
        "session_id": "s",
        "cwd": cwd,
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {
                    "header": "Database",
                    "question": "Which database backend should we use?",
                    "multiSelect": False,
                    "options": [
                        {"label": "Postgres", "description": "Relational"},
                        {"label": "SQLite", "description": "Embedded"},
                    ],
                }
            ]
        },
        "tool_response": {
            "answers": [
                {
                    "header": "Database",
                    "question": "Which database backend should we use?",
                    "selected": ["Postgres"],
                }
            ]
        },
    }


def _exit_payload(cwd: str) -> dict[str, object]:
    return {
        "session_id": "s",
        "cwd": cwd,
        "tool_name": "ExitPlanMode",
        "tool_input": {"plan": "1. Build\n2. Run"},
        "tool_response": {"isAgent": False},
    }


def _enter_payload(cwd: str) -> dict[str, object]:
    return {
        "session_id": "s",
        "cwd": cwd,
        "tool_name": "EnterPlanMode",
        "tool_input": {"plan": "draft plan"},
        "tool_response": {},
    }


def test_run_model_has_tool_decisions_field_default() -> None:
    model = RunModel(
        run_id="r", title="t", description="d", created_at="x", updated_at="x",
        selected_profile="process", requested_profile="process", profile_uri="", mode="monitored",
    )
    assert model.tool_decisions == []


def test_ask_user_question_decision_populated(tmp_path: Path) -> None:
    state_dir = _seed_run(tmp_path)
    _append_post_tool(state_dir, _ask_payload(str(tmp_path)))
    model = build_run_model(state_dir)
    assert len(model.tool_decisions) == 1
    d = model.tool_decisions[0]
    assert d["tool"] == "AskUserQuestion"
    assert d["question"] == "Which database backend should we use?"
    assert d["options"] == ["Postgres", "SQLite"]
    assert d["answer"] == "Postgres"
    assert d["plan"] is None
    assert isinstance(d["sequence"], int)
    assert isinstance(d["timestamp"], str) and d["timestamp"]


def test_plan_mode_decisions_populated(tmp_path: Path) -> None:
    state_dir = _seed_run(tmp_path)
    _append_post_tool(state_dir, _exit_payload(str(tmp_path)))
    _append_post_tool(state_dir, _enter_payload(str(tmp_path)))
    model = build_run_model(state_dir)
    by_tool = {d["tool"]: d for d in model.tool_decisions}
    assert set(by_tool) == {"ExitPlanMode", "EnterPlanMode"}
    assert by_tool["ExitPlanMode"]["plan"] == "1. Build\n2. Run"
    assert by_tool["ExitPlanMode"]["question"] is None
    assert by_tool["ExitPlanMode"]["options"] == []
    assert by_tool["ExitPlanMode"]["answer"] is None
    assert by_tool["EnterPlanMode"]["plan"] == "draft plan"


def test_decision_tools_not_double_counted_as_tool_uses(tmp_path: Path) -> None:
    state_dir = _seed_run(tmp_path)
    _append_post_tool(state_dir, _ask_payload(str(tmp_path)))
    _append_post_tool(state_dir, _exit_payload(str(tmp_path)))
    model = build_run_model(state_dir)
    names = {t["tool_name"] for t in model.tool_uses}
    assert "AskUserQuestion" not in names
    assert "ExitPlanMode" not in names
    assert len(model.tool_decisions) == 2


def test_multi_question_ask_flattened(tmp_path: Path) -> None:
    state_dir = _seed_run(tmp_path)
    payload = {
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {"question": "Q1?", "options": [{"label": "A"}, {"label": "B"}]},
                {"question": "Q2?", "options": [{"label": "C"}]},
            ]
        },
        "tool_response": {
            "answers": [
                {"selected": ["A"]},
                {"selected": ["C"]},
            ]
        },
    }
    _append_post_tool(state_dir, payload)
    model = build_run_model(state_dir)
    assert len(model.tool_decisions) == 1
    d = model.tool_decisions[0]
    assert d["question"] == "Q1?; Q2?"
    assert d["options"] == ["A", "B", "C"]
    assert d["answer"] == "A; C"


def test_decision_extraction_robust_to_missing_keys(tmp_path: Path) -> None:
    state_dir = _seed_run(tmp_path)
    # AskUserQuestion with empty content yields no decision; plan-mode with no plan yields none.
    _append_post_tool(
        state_dir,
        {"session_id": "s", "cwd": str(tmp_path), "tool_name": "AskUserQuestion",
         "tool_input": {}, "tool_response": {}},
    )
    _append_post_tool(
        state_dir,
        {"session_id": "s", "cwd": str(tmp_path), "tool_name": "ExitPlanMode",
         "tool_input": {}, "tool_response": {}},
    )
    model = build_run_model(state_dir)
    assert model.tool_decisions == []


def test_unit_extract_direct_from_journal_dict(tmp_path: Path) -> None:
    """Build a journal by appending events, reload, and confirm the contract shape exactly."""
    state_dir = _seed_run(tmp_path)
    _append_post_tool(state_dir, _ask_payload(str(tmp_path)))
    model = build_run_model(state_dir)
    d = model.tool_decisions[0]
    assert set(d.keys()) == {
        "sequence", "timestamp", "tool", "question", "options", "answer", "plan",
    }
    # round-trips through JSON cleanly (it ends up serialized in the crate)
    json.dumps(d)
