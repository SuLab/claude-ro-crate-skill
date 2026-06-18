import json
from pathlib import Path

from ro_crate_run.cli import main


def test_step_events_promote_to_provenance_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "workflow.cwl").write_text("class: Workflow\ninputs: []\noutputs: []\nsteps: {}\n")
    assert main(["start", "Provenance demo", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["input", "workflow.cwl", "--role", "workflow-definition", "--copy"]) == 0
    assert (
        main(
            [
                "step",
                "start",
                "normalize",
                "--workflow-step",
                "normalize",
                "--description",
                "Normalize counts",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "run",
                "--step",
                "normalize",
                "--outputs",
                "normalized.tsv",
                "--",
                "python3",
                "-c",
                "open('normalized.tsv','w').write('n')",
            ]
        )
        == 0
    )
    assert main(["step", "end", "normalize", "--status", "completed"]) == 0
    assert main(["checkpoint", "--profile", "auto"]) == 0

    data = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())
    entities = data["@graph"]
    root = next(e for e in entities if e["@id"] == "./")
    assert {"@id": "https://w3id.org/ro/wfrun/provenance/0.5"} in root["conformsTo"]
    assert any(e.get("@type") == "HowToStep" for e in entities)
    assert any(e.get("@type") == "ControlAction" for e in entities)
