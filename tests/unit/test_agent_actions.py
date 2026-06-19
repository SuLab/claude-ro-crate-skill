"""The Claude agent's own actions (file edits, etc.) are materialized as the workflow."""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.journal import EventWriter
from tests.graph_helpers import assert_no_dangling_refs


def _types(entity: dict) -> list:
    t = entity.get("@type")
    return [t] if isinstance(t, str) else (t or [])


def _append(state_dir: Path, etype: str, payload: dict) -> None:
    EventWriter(state_dir).append(etype, payload, source_kind="claude_hook", inferred=True)


def test_agent_file_edits_materialize_as_actions(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "summarize.py").write_text("x = 1\n")
    assert main(["start", "Edits", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    sd = tmp_path / ".ro-crate-run"
    _append(sd, "file.created", {"path": str(tmp_path / "summarize.py"), "tool_name": "Write"})
    (tmp_path / "summarize.py").write_text("x = 2\n")
    _append(sd, "file.modified", {"path": str(tmp_path / "summarize.py"), "tool_name": "Edit"})
    assert main(["checkpoint"]) == 0

    graph = json.loads((sd / "ro-crate" / "ro-crate-metadata.json").read_text())["@graph"]
    assert_no_dangling_refs(graph)

    file_actions = [e for e in graph if str(e.get("@id", "")).startswith("#file-action/")]
    types = {t for e in file_actions for t in _types(e)}
    assert "CreateAction" in types, f"no CreateAction for the Write; types={types}"
    assert "UpdateAction" in types, f"no UpdateAction for the Edit; types={types}"
    # The edited file is a real File entity referenced by the actions.
    assert any(e.get("@id") == "summarize.py" and "File" in _types(e) for e in graph)
    for fa in file_actions:
        assert (fa.get("result") or fa.get("object")), "file action missing result/object File ref"

    # Editing files is structured agent work -> auto-promoted to a workflow profile,
    # with the synthesized agent-actions workflow as mainEntity.
    root = next(e for e in graph if e.get("@id") == "./")
    conforms = root["conformsTo"]
    conforms = conforms if isinstance(conforms, list) else [conforms]
    assert any("/workflow/" in c["@id"] or "/provenance/" in c["@id"] for c in conforms)
    assert root.get("mainEntity", {}).get("@id") == "#workflow/agent-actions"


def test_accept_reject_and_phases_materialize(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "AR", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["phase", "analysis"]) == 0
    assert main(["run", "--", "python3", "-c", "print('x')"]) == 0
    assert main(["phase", "complete", "analysis"]) == 0
    assert main(["accept", "Looks good"]) == 0
    assert main(["reject", "Second attempt wrong"]) == 0
    assert main(["checkpoint"]) == 0

    graph = json.loads((tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json").read_text())["@graph"]
    assert_no_dangling_refs(graph)
    assert any("AssessAction" in _types(e) for e in graph), "accept/reject not materialized"
    assert any(str(e.get("@id", "")).startswith("#phase/") for e in graph), "phase not materialized"


def test_synthesized_workflow_weaves_agent_actions_as_steps(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # An edit-only session (no rcr run): the synthesized workflow's steps ARE the agent's
    # file edits, in order, each linked via a ControlAction; a workflow-level action uses
    # the workflow as instrument (L3) and is agented to the AI.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("v1\n")
    assert main(["start", "Weave", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    sd = tmp_path / ".ro-crate-run"
    _append(sd, "file.created", {"path": str(tmp_path / "a.py"), "tool_name": "Write"})
    (tmp_path / "a.py").write_text("v2\n")
    _append(sd, "file.modified", {"path": str(tmp_path / "a.py"), "tool_name": "Edit"})
    assert main(["checkpoint"]) == 0

    graph = json.loads((sd / "ro-crate" / "ro-crate-metadata.json").read_text())["@graph"]
    assert_no_dangling_refs(graph)
    wf = next(e for e in graph if e.get("@id") == "#workflow/agent-actions")
    steps = wf.get("step") or []
    assert len(steps) == 2, f"workflow should have 2 woven steps, got {steps}"
    howto_ids = {e["@id"] for e in graph if "HowToStep" in _types(e)}
    assert all(s["@id"] in howto_ids for s in steps), "workflow step refs must resolve to HowToSteps"
    controls = [e for e in graph if "ControlAction" in _types(e)]
    assert len(controls) >= 2
    assert all(
        str((c.get("object") or {}).get("@id", "")).startswith("#file-action/") for c in controls
    ), "each ControlAction should control a file-action"
    wf_actions = [e for e in graph if (e.get("instrument") or {}).get("@id") == "#workflow/agent-actions"]
    assert wf_actions, "no action uses the workflow as instrument (L3)"
    assert wf_actions[0]["agent"]["@id"] == "#actor/claude-code"


def test_rcr_tooling_is_not_a_raw_command(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The agent invokes rcr via its full skill path (Bash); that provenance tooling must
    # NOT be materialized as a raw-command workflow step. A genuine raw command must.
    monkeypatch.chdir(tmp_path)
    assert main(["start", "T", "--mode", "advisory", "--profile", "auto", "--no-checkpoint"]) == 0
    sd = tmp_path / ".ro-crate-run"
    _append(sd, "tool.completed",
            {"tool_name": "Bash", "tool_input": {"command": "/home/x/scripts/rcr checkpoint"}})
    _append(sd, "tool.completed",
            {"tool_name": "Bash", "tool_input": {"command": "wc -l data.csv"}})
    assert main(["checkpoint"]) == 0
    graph = json.loads((sd / "ro-crate" / "ro-crate-metadata.json").read_text())["@graph"]
    raw = [str(e.get("name", "")) for e in graph if str(e.get("@id", "")).startswith("#raw-command/")]
    assert any("wc -l" in n for n in raw), f"genuine raw command missing: {raw}"
    assert not any("rcr" in n for n in raw), f"rcr tooling leaked as a raw-command: {raw}"


def test_workflow_action_with_failed_command_carries_error(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A workflow run with a failed command -> the workflow-level action is
    # FailedActionStatus and MUST carry an error (L3), so validation stays clean.
    monkeypatch.chdir(tmp_path)
    assert main(["start", "B", "--mode", "advisory", "--profile", "workflow", "--no-checkpoint"]) == 0
    assert main(["run", "--", "python3", "-c", "import sys; sys.exit(3)"]) != 0
    assert main(["run", "--", "python3", "-c", "print('ok')"]) == 0
    assert main(["checkpoint"]) == 0
    graph = json.loads((tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json").read_text())["@graph"]
    wf_action = next(
        e for e in graph
        if str((e.get("instrument") or {}).get("@id", "")).startswith("#workflow/")
        and "Failed" in str((e.get("actionStatus") or {}).get("@id", ""))
    )
    assert wf_action.get("error"), "failed workflow-level action missing error"
