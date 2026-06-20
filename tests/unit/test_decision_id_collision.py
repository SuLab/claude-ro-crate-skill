"""A human decision and a tool decision whose counters coincide must not merge.

build_notes_decisions mints ``#decision/<index>`` (1-based over public human decisions)
while _build_tool_decisions mints ``#tool-decision/<sequence>`` (raw event sequence). The
two namespaces are disjoint, so a human decision at index N and a tool decision at event
sequence N stay distinct entities with distinct @types after the @graph is deduped.
"""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.materialize.builder import write_crate
from ro_crate_run.materialize.run_model import build_run_model
from tests.graph_helpers import assert_no_dangling_refs


def _graph(tmp_path: Path) -> list[dict]:
    p = tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json"
    return json.loads(p.read_text())["@graph"]


def _by_id(graph: list[dict]) -> dict[str, dict]:
    return {e["@id"]: e for e in graph if "@id" in e}


def test_human_and_tool_decision_same_counter_do_not_merge(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Collide", "--profile", "process", "--no-checkpoint"]) == 0
    assert main(
        ["run", "--outputs", "out.txt", "--",
         "python3", "-c", "open('out.txt','w').write('y')"]
    ) == 0

    state_dir = tmp_path / ".ro-crate-run"
    model = build_run_model(state_dir, None)
    # A public human decision becomes #decision/1 (first public decision, 1-based).
    model.decisions = [  # type: ignore[attr-defined]
        {"text": "ship it", "rationale": "looks good", "visibility": "public"}
    ]
    # A tool decision whose event sequence collides with that index (1).
    model.agent_activity.tool_decisions = [  # type: ignore[attr-defined]
        {
            "sequence": 1,
            "timestamp": "2026-06-20T00:00:00Z",
            "tool": "AskUserQuestion",
            "question": "Q?",
            "options": ["x", "y"],
            "answer": "x",
        }
    ]
    write_crate(state_dir, model)
    graph = _graph(tmp_path)
    by_id = _by_id(graph)

    # Both entities survive as separate nodes under disjoint @ids.
    assert "#decision/1" in by_id
    assert "#tool-decision/1" in by_id

    human = by_id["#decision/1"]
    tool = by_id["#tool-decision/1"]
    # The human decision is a CreativeWork; the tool decision is a ChooseAction — and the
    # merge would have fused these @types onto one mangled entity.
    assert human["@type"] == "CreativeWork"
    assert tool["@type"] == "ChooseAction"
    assert human["text"] == "ship it"
    assert tool["agent"] == {"@id": "#actor/human"}
    assert "agent" not in human
    assert "text" not in tool

    assert_no_dangling_refs(graph)
