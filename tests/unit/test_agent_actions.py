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
