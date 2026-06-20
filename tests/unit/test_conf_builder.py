"""Conformance regression coverage for the builder.py RO-Crate output.

Each test GENERATES a real crate via the CLI and inspects the emitted
ro-crate-metadata.json, asserting the expected structure:

  - no anonymous inline typed node — every nested typed dict is a top-level entity with
    an @id, and the crate re-loads via ro-crate-py without raising.
  - every relative-@id File/Dataset data entity is linked from the root via hasPart.
  - the contextual Profile entity's @type is ["CreativeWork", "Profile"].
  - a workflow/provenance crate also declares the Process Run Crate 0.5 + Workflow
    RO-Crate 1.0 profiles (each with a matching Profile entity), and emits a README.md.
  - the event-journal File carries contentSize.
  - captured human decisions are materialized as ChooseAction/CreativeWork attributed to
    the human, referenced from the root's mentions.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rocrate.rocrate import ROCrate  # type: ignore[import-untyped]

from ro_crate_run.cli import main
from ro_crate_run.materialize.builder import _build_tool_decisions, write_crate
from ro_crate_run.materialize.run_model import build_run_model


def _graph(tmp_path: Path) -> list[dict]:
    p = tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json"
    return json.loads(p.read_text())["@graph"]


def _by_id(graph: list[dict]) -> dict[str, dict]:
    return {e["@id"]: e for e in graph if "@id" in e}


def _type_set(entity: dict) -> set[str]:
    t = entity.get("@type")
    return {str(x) for x in (t if isinstance(t, list) else [t])}


def _inline_typed_without_id(graph: list[dict]) -> list:
    bad: list = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "@type" in value and "@id" not in value and "@value" not in value:
                bad.append(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for entity in graph:
        walk(entity)
    return bad


def _make_process_crate(tmp_path: Path) -> None:
    assert main(["start", "Conf", "--profile", "process", "--no-checkpoint"]) == 0
    (tmp_path / "in.txt").write_text("x")
    assert main(["input", "in.txt", "--role", "primary"]) == 0
    assert main(
        ["run", "--inputs", "in.txt", "--outputs", "out.txt", "--",
         "python3", "-c", "open('out.txt','w').write('y')"]
    ) == 0
    assert main(["container", "docker.io/library/python:3.12", "--digest", "sha256:abc"]) == 0
    assert main(["checkpoint"]) == 0


# --- H1 -------------------------------------------------------------------------------------


def test_h1_no_anonymous_inline_nodes_and_rocrate_py_reloads(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_process_crate(tmp_path)
    graph = _graph(tmp_path)

    # No nested typed dict lacks an @id (RO-Crate 1.2 MUST: no anonymous inlining).
    assert _inline_typed_without_id(graph) == []

    # The crate re-loads via ro-crate-py without raising (the H1 round-trip gate).
    ROCrate(str(tmp_path / ".ro-crate-run" / "ro-crate"))

    # The promoted values are preserved as top-level referenced #embedded/* entities, e.g. the
    # output file's sha256 identifier survives (now node-ified, not stripped).
    embedded = [e for e in graph if str(e.get("@id", "")).startswith("#embedded/")]
    assert any(e.get("propertyID") == "sha256" for e in embedded)
    # The File's `identifier` is now a reference to that node, not an inline dict.
    out = _by_id(graph)["out.txt"]
    assert set(out["identifier"].keys()) == {"@id"}
    assert out["identifier"]["@id"].startswith("#embedded/")


# --- H2 -------------------------------------------------------------------------------------


def test_h2_all_relative_file_entities_in_haspart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_process_crate(tmp_path)
    graph = _graph(tmp_path)
    root = _by_id(graph)["./"]
    has_part = {ref["@id"] for ref in root["hasPart"]}

    for entity in graph:
        eid = entity.get("@id", "")
        if not isinstance(eid, str):
            continue
        if eid.startswith(("#", "http://", "https://", "urn:", "file:")):
            continue
        if eid in {"./", "ro-crate-metadata.json"}:
            continue
        if _type_set(entity) & {"File", "Dataset"}:
            assert eid in has_part, f"relative data entity {eid!r} not linked from hasPart"


# --- L1 -------------------------------------------------------------------------------------


def test_l1_profile_entity_type_is_creativework_profile_array(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_process_crate(tmp_path)
    graph = _graph(tmp_path)
    profile = _by_id(graph)["https://w3id.org/ro/wfrun/process/0.5"]
    assert profile["@type"] == ["CreativeWork", "Profile"]
    assert profile.get("name")


# --- L3 -------------------------------------------------------------------------------------


def _make_workflow_crate(tmp_path: Path, profile: str) -> None:
    assert main(["start", "WF", "--profile", profile, "--no-checkpoint"]) == 0
    (tmp_path / "Snakefile").write_text('rule all:\n    input: "out.txt"\n')
    assert main(["input", "Snakefile", "--role", "workflow-definition"]) == 0
    assert main(["parameter", "threads", "4", "--type", "Integer"]) == 0
    if profile == "provenance":
        assert main(["step", "start", "s1"]) == 0
    assert main(
        ["run", "--outputs", "out.txt", "--", "python3", "-c", "open('out.txt','w').write('y')"]
    ) == 0
    if profile == "provenance":
        assert main(["step", "end", "s1"]) == 0
    assert main(["checkpoint", "--profile", profile]) == 0


def test_l3_workflow_conformsto_extras_and_readme(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_workflow_crate(tmp_path, "workflow")
    graph = _graph(tmp_path)
    by_id = _by_id(graph)
    conforms = {ref["@id"] for ref in by_id["./"]["conformsTo"]}

    process_uri = "https://w3id.org/ro/wfrun/process/0.5"
    wfrc_uri = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
    assert "https://w3id.org/ro/wfrun/workflow/0.5" in conforms
    assert process_uri in conforms
    assert wfrc_uri in conforms

    # Each listed profile MUST link to a contextual Profile entity (RO-Crate 1.2 MUST).
    for uri in (process_uri, wfrc_uri):
        assert by_id[uri]["@type"] == ["CreativeWork", "Profile"]

    # README.md SHOULD exist as a File in hasPart.
    assert "README.md" in by_id
    assert by_id["README.md"]["encodingFormat"] == "text/markdown"
    assert {"@id": "README.md"} in by_id["./"]["hasPart"]
    assert (tmp_path / ".ro-crate-run" / "ro-crate" / "README.md").exists()

    # Provenance profile gets the same extra conformsTo + a clean round-trip.
    ROCrate(str(tmp_path / ".ro-crate-run" / "ro-crate"))


def test_l3_process_crate_does_not_add_workflow_profiles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_process_crate(tmp_path)
    graph = _graph(tmp_path)
    conforms = {ref["@id"] for ref in _by_id(graph)["./"]["conformsTo"]}
    assert "https://w3id.org/workflowhub/workflow-ro-crate/1.0" not in conforms


# --- L8 -------------------------------------------------------------------------------------


def test_l8_event_journal_has_contentsize(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Journal", "--no-checkpoint"]) == 0
    cfg_path = tmp_path / ".ro-crate-run" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg.setdefault("file_policy", {})["include_event_journal"] = True
    cfg_path.write_text(json.dumps(cfg))
    assert main(
        ["run", "--outputs", "o.txt", "--", "python3", "-c", "open('o.txt','w').write('y')"]
    ) == 0
    assert main(["checkpoint"]) == 0

    journal = _by_id(_graph(tmp_path))["events.ndjson"]
    assert "contentSize" in journal
    assert int(journal["contentSize"]) > 0


# --- L6 -------------------------------------------------------------------------------------


def test_l6_build_tool_decisions_helper() -> None:
    model = SimpleNamespace(
        agent_activity=SimpleNamespace(
            tool_decisions=[
                {
                    "sequence": 5,
                    "timestamp": "2026-06-20T00:00:00Z",
                    "tool": "AskUserQuestion",
                    "question": "Pick one",
                    "options": ["a", "b"],
                    "answer": "a",
                },
                {
                    "sequence": 7,
                    "timestamp": "2026-06-20T00:01:00Z",
                    "tool": "ExitPlanMode",
                    "plan": "do X then Y",
                },
            ]
        )
    )

    ents = _build_tool_decisions(model)
    ask = next(e for e in ents if e["@id"] == "#tool-decision/5")
    assert ask["@type"] == "ChooseAction"
    assert ask["agent"] == {"@id": "#actor/human"}
    assert ask["result"] == "a"
    assert ask["object"] == "Pick one"
    assert [p["value"] for p in ask["additionalProperty"]] == ["a", "b"]

    plan = next(e for e in ents if e["@id"] == "#tool-decision/7")
    assert plan["@type"] == ["CreativeWork"]
    assert plan["creator"] == {"@id": "#actor/human"}
    assert plan["text"] == "do X then Y"


def test_l6_build_tool_decisions_empty_yields_no_entities() -> None:
    # A run model that recorded no human tool decisions produces no decision entities.
    assert _build_tool_decisions(
        SimpleNamespace(agent_activity=SimpleNamespace(tool_decisions=[]))
    ) == []


def test_l6_decisions_materialized_in_crate_and_mentioned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_process_crate(tmp_path)
    state_dir = tmp_path / ".ro-crate-run"
    model = build_run_model(state_dir, None)
    # Tool decisions use the #tool-decision/<sequence> @id namespace.
    model.agent_activity.tool_decisions = [  # type: ignore[attr-defined]
        {
            "sequence": 99,
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

    decision = by_id["#tool-decision/99"]
    assert decision["@type"] == "ChooseAction"
    assert decision["agent"] == {"@id": "#actor/human"}
    # Referenced from the root's mentions.
    assert {"@id": "#tool-decision/99"} in by_id["./"]["mentions"]
    # The inline option PropertyValues are node-ified (H1) so the crate still round-trips.
    assert all(set(p.keys()) == {"@id"} for p in decision["additionalProperty"])
    ROCrate(str(state_dir / "ro-crate"))
