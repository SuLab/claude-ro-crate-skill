import json
from pathlib import Path

from ro_crate_run.cli import main


def test_snakemake_workflow_promotes_to_workflow_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Snakefile").write_text(
        "rule all:\n"
        "    output: 'results/out.txt'\n"
        "    shell: 'mkdir -p results && echo ok > results/out.txt'\n"
    )
    assert main(["start", "Workflow demo", "--profile", "auto", "--no-checkpoint"]) == 0
    assert main(["input", "Snakefile", "--role", "workflow-definition", "--copy"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "results/out.txt",
                "--",
                "python3",
                "-c",
                "import pathlib; pathlib.Path('results').mkdir(exist_ok=True); pathlib.Path('results/out.txt').write_text('ok')",
            ]
        )
        == 0
    )
    assert main(["checkpoint", "--profile", "auto"]) == 0

    data = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())
    entities = {e["@id"]: e for e in data["@graph"]}
    root = entities["./"]
    assert {"@id": "https://w3id.org/ro/wfrun/workflow/0.5"} in root["conformsTo"]
    workflow_entities = [
        e
        for e in data["@graph"]
        if "ComputationalWorkflow" in (e.get("@type") if isinstance(e.get("@type"), list) else [])
    ]
    assert len(workflow_entities) == 1
    assert root["mainEntity"]["@id"] == workflow_entities[0]["@id"]
