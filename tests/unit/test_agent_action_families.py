"""Regression coverage for the agent-action materialization families (SPEC §16).

Each family is exercised end-to-end: ``rcr start`` -> append the triggering hook
event(s) via :class:`EventWriter` -> ``rcr checkpoint`` -> load the crate ``@graph``
and assert the family's entity is PRESENT with the right ``@type``/action fields.

Assertions are deliberately presence-based (not exact counts/dimensions): the
synthesized workflow shape is evolving elsewhere, so these tests pin the family
contract (id prefix, @type, action status/timing) rather than the graph layout.
"""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.journal import EventWriter
from tests.graph_helpers import assert_no_dangling_refs


def _types(entity: dict) -> list:
    t = entity.get("@type")
    return [t] if isinstance(t, str) else (t or [])


def _status_id(entity: dict) -> str:
    st = entity.get("actionStatus")
    if isinstance(st, dict):
        return str(st.get("@id", ""))
    return str(st or "")


def _append(state_dir: Path, etype: str, payload: dict) -> None:
    EventWriter(state_dir).append(etype, payload, source_kind="claude_hook", inferred=True)


def _start(tmp_path: Path) -> Path:
    """Run ``rcr start`` (advisory/auto, no auto-checkpoint) and return the state dir."""
    assert main(
        ["start", "Agent actions", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]
    ) == 0
    return tmp_path / ".ro-crate-run"


def _graph(state_dir: Path) -> list:
    crate = state_dir / "ro-crate" / "ro-crate-metadata.json"
    return json.loads(crate.read_text())["@graph"]


def _by_prefix(graph: list, prefix: str) -> list:
    return [e for e in graph if str(e.get("@id", "")).startswith(prefix)]


def _assert_action_shape(entity: dict) -> None:
    assert entity.get("startTime"), f"{entity.get('@id')} missing startTime"
    assert entity.get("endTime"), f"{entity.get('@id')} missing endTime"
    assert _status_id(entity), f"{entity.get('@id')} missing actionStatus"


# ---------------------------------------------------------------------------
# Raw Bash -> #raw-command/{seq} CreateAction  (rcr-wrapped commands excluded)
# ---------------------------------------------------------------------------


def test_raw_bash_command_materializes_create_action(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    _append(
        sd,
        "tool.completed",
        {"tool_name": "Bash", "tool_input": {"command": "wc -l data.csv"}},
    )
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)

    raw = _by_prefix(graph, "#raw-command/")
    assert raw, "raw Bash command not materialized as #raw-command/*"
    action = raw[0]
    assert "CreateAction" in _types(action), f"expected CreateAction; types={_types(action)}"
    _assert_action_shape(action)
    assert action.get("agent", {}).get("@id") == "#actor/claude-code"
    # The CreateAction's instrument resolves to an emitted SoftwareApplication (no dangling ref).
    instrument_id = action.get("instrument", {}).get("@id")
    assert instrument_id, "raw-command action missing instrument"
    assert any(e.get("@id") == instrument_id for e in graph)


def test_rcr_wrapped_bash_excluded_from_raw_commands(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    # An rcr-wrapped command is captured as execution.command.* elsewhere; the reducer
    # must NOT also emit a #raw-command CreateAction for it.
    _append(
        sd,
        "tool.completed",
        {"tool_name": "Bash", "tool_input": {"command": "rcr status"}},
    )
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)
    assert _by_prefix(graph, "#raw-command/") == [], "rcr-wrapped Bash leaked into #raw-command/*"


# ---------------------------------------------------------------------------
# Subagent -> #subagent/{seq} OrganizeAction
# ---------------------------------------------------------------------------


def test_subagent_task_materializes_organize_action(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    _append(
        sd,
        "agent.task.created",
        {
            "task_id": "t-1",
            "subagent_type": "Explore",
            "description": "Search the codebase for the parser entrypoint.",
        },
    )
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)

    subagents = _by_prefix(graph, "#subagent/")
    assert subagents, "subagent task not materialized as #subagent/*"
    action = subagents[0]
    assert "OrganizeAction" in _types(action), f"expected OrganizeAction; types={_types(action)}"
    _assert_action_shape(action)
    assert action.get("agent", {}).get("@id") == "#actor/claude-code"


# ---------------------------------------------------------------------------
# Blocked tool call -> #blocked/{seq} Action + FailedActionStatus + error
# ---------------------------------------------------------------------------


def test_blocked_tool_materializes_failed_action(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    _append(
        sd,
        "tool.blocked",
        {
            "tool_name": "Bash",
            "command": "rm -rf .ro-crate-run",
            "reason": "evidence-destroying command blocked by policy",
        },
    )
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)

    blocked = _by_prefix(graph, "#blocked/")
    assert blocked, "blocked tool call not materialized as #blocked/*"
    action = blocked[0]
    assert "Action" in _types(action), f"expected Action; types={_types(action)}"
    _assert_action_shape(action)
    assert "Failed" in _status_id(action), f"expected FailedActionStatus; got {_status_id(action)}"
    assert action.get("error"), "blocked action missing error property"


# ---------------------------------------------------------------------------
# User prompt -> #prompt/{seq} CreativeWork
# ---------------------------------------------------------------------------


def test_human_prompt_materializes_creative_work(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    _append(sd, "human.prompt", {"prompt": "Please count the rows in data.csv."})
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)

    prompts = _by_prefix(graph, "#prompt/")
    assert prompts, "human prompt not materialized as #prompt/*"
    work = prompts[0]
    assert "CreativeWork" in _types(work), f"expected CreativeWork; types={_types(work)}"
    assert work.get("text"), "prompt CreativeWork missing text"
    # CreativeWork is about the crate root (a dangling-ref-safe reference).
    assert work.get("about", {}).get("@id") == "./"


# ---------------------------------------------------------------------------
# Non-Bash tool -> #tool-use/{name} Action
# ---------------------------------------------------------------------------


def test_tool_use_materializes_action(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    _append(sd, "tool.completed", {"tool_name": "Read"})
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)

    tool_uses = _by_prefix(graph, "#tool-use/")
    assert tool_uses, "non-Bash tool use not materialized as #tool-use/*"
    assert any(e.get("@id") == "#tool-use/Read" for e in tool_uses), \
        f"expected #tool-use/Read; got {[e.get('@id') for e in tool_uses]}"
    action = next(e for e in tool_uses if e.get("@id") == "#tool-use/Read")
    assert "Action" in _types(action), f"expected Action; types={_types(action)}"
    _assert_action_shape(action)
    assert action.get("agent", {}).get("@id") == "#actor/claude-code"


# ---------------------------------------------------------------------------
# Housekeeping (cwd change) -> #housekeeping/{seq} Action
# ---------------------------------------------------------------------------


def test_housekeeping_cwd_change_materializes_action(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    sd = _start(tmp_path)
    _append(sd, "environment.cwd.changed", {"new_cwd": str(tmp_path / "subdir")})
    assert main(["checkpoint"]) == 0

    graph = _graph(sd)
    assert_no_dangling_refs(graph)

    housekeeping = _by_prefix(graph, "#housekeeping/")
    assert housekeeping, "cwd change not materialized as #housekeeping/*"
    action = housekeeping[0]
    assert "Action" in _types(action), f"expected Action; types={_types(action)}"
    _assert_action_shape(action)
    assert action.get("agent", {}).get("@id") == "#actor/claude-code"
