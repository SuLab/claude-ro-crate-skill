"""Crates must contain — and make discoverable — all expected information (the directive).

Regression coverage for materializer gaps found by adversarial verification:
  - a declared input (rcr input) was emitted but orphaned (unreachable from root);
  - the file `existence` classification (observed/generated/expected/missing/...) was
    never materialized into the graph (lived only in state.json);
  - a declared output's --description / --existence were clobbered by the command-output
    FilePlan;
  - a dependency manifest was a bare File with no recorded sha256.
"""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main
from tests.graph_helpers import assert_declared_io_reachable, assert_no_dangling_refs, reachable_ids


def _graph(tmp_path: Path) -> list:
    p = tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json"
    return json.loads(p.read_text())["@graph"]


def _by_id(graph: list) -> dict:
    return {e.get("@id"): e for e in graph}


def _props(entity: dict) -> dict:
    ap = entity.get("additionalProperty")
    ap = ap if isinstance(ap, list) else ([ap] if ap else [])
    return {p.get("propertyID"): p.get("value") for p in ap}


def test_declared_input_is_reachable_and_carries_existence(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    assert main(["start", "Proc", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["input", "data.csv", "--role", "dataset", "--existence", "observed local"]) == 0
    assert main(["run", "--outputs", "rows.txt", "--", "python3", "-c",
                 "open('rows.txt','w').write('x\\n')"]) == 0
    assert main(["checkpoint"]) == 0

    graph = _graph(tmp_path)
    assert_no_dangling_refs(graph)
    assert_declared_io_reachable(graph)  # would FAIL before the fix (data.csv orphaned)

    data = _by_id(graph)["data.csv"]
    assert "data.csv" in reachable_ids(graph), "declared input is an orphan"
    assert _props(data).get("existence") == "observed local", "input existence not materialized"


def test_declared_output_flags_survive_command_output(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # An output declared with --description/--existence that is ALSO produced by the command
    # must keep the user's flags (the generic command-output plan must not clobber them).
    monkeypatch.chdir(tmp_path)
    assert main(["start", "P", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["output", "rows.txt", "--description", "row dump", "--existence", "generated"]) == 0
    assert main(["run", "--outputs", "rows.txt", "--", "python3", "-c",
                 "open('rows.txt','w').write('x\\n')"]) == 0
    assert main(["output", "future.txt", "--description", "later", "--existence", "expected"]) == 0
    assert main(["checkpoint"]) == 0

    graph = _graph(tmp_path)
    rows = _by_id(graph)["rows.txt"]
    assert rows["description"] == "row dump", f"user --description clobbered: {rows['description']!r}"
    assert _props(rows).get("existence") == "generated", "output existence not materialized"
    future = _by_id(graph)["future.txt"]
    assert _props(future).get("existence") == "expected"


def test_dependency_manifest_has_sha256_and_is_reachable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\nrich>=13\n")
    assert main(["start", "Deps", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    # `rcr software` triggers the lockfile scan.
    assert main(["software", "python3", "--version", "3.12.3"]) == 0
    assert main(["checkpoint"]) == 0

    graph = _graph(tmp_path)
    assert_no_dangling_refs(graph)
    req = _by_id(graph).get("requirements.txt")
    assert req is not None, "dependency manifest not emitted"
    digest = (req.get("identifier") or {}).get("value", "")
    assert len(digest) == 64, f"dependency manifest missing sha256: {req}"
    assert "requirements.txt" in reachable_ids(graph), "dependency manifest is an orphan"
