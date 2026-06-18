from __future__ import annotations

from pathlib import Path

from ro_crate_run.cli import main
from tests.graph_helpers import assert_no_dangling_refs


def test_provenance_checkpoint_has_control_action(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / "workflow.cwl").write_text("class: Workflow\ninputs: []\noutputs: []\nsteps: {}\n")
    assert main(["start", "Provenance unit", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["input", "workflow.cwl", "--role", "workflow-definition"]) == 0
    assert main(["step", "start", "s1"]) == 0
    assert (
        main(
            [
                "run",
                "--step",
                "s1",
                "--outputs",
                "a.txt",
                "--",
                "python3",
                "-c",
                "open('a.txt','w').write('a')",
            ]
        )
        == 0
    )
    assert main(["step", "end", "s1"]) == 0
    assert main(["checkpoint", "--profile", "auto"]) == 0
    assert (tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").exists()


def test_provenance_crate_steps_and_control_actions(tmp_path: Path, monkeypatch: object) -> None:
    import json

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / "wf.cwl").write_text("cwlVersion: v1.2\n")
    assert main(["start", "PV", "--profile", "provenance", "--no-checkpoint"]) == 0
    assert main(["input", "wf.cwl", "--role", "workflow-definition"]) == 0
    assert main(["step", "start", "normalize"]) == 0
    assert (
        main(
            [
                "run",
                "--step",
                "normalize",
                "--outputs",
                "mid.txt",
                "--",
                "python3",
                "-c",
                "open('mid.txt','w').write('m')",
            ]
        )
        == 0
    )
    assert main(["step", "end", "normalize"]) == 0
    assert main(["checkpoint", "--profile", "provenance"]) == 0
    graph = json.loads(
        (tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text()
    )["@graph"]
    types = [e.get("@type") for e in graph]
    assert "HowToStep" in types
    assert "ControlAction" in types
    assert_no_dangling_refs(graph)
