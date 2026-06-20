from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.adapters.imports import import_existing_ro_crate
from tests.graph_helpers import assert_no_dangling_refs


def test_import_existing_ro_crate_creates_workflow_events(tmp_path: Path) -> None:
    crate = tmp_path / "crate"
    crate.mkdir()
    (crate / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.2/context"],
                "@graph": [
                    {
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                    },
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "name": "Imported",
                        "description": "Imported workflow crate",
                        "datePublished": "2026-06-17",
                        "license": {"@id": "https://creativecommons.org/licenses/by/4.0/"},
                        "mainEntity": {"@id": "workflow.cwl"},
                    },
                    {
                        "@id": "workflow.cwl",
                        "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
                        "name": "workflow.cwl",
                    },
                ],
            }
        )
    )

    events = import_existing_ro_crate(crate)

    assert [e["event_type"] for e in events] == ["workflow.identified"]
    assert events[0]["payload"]["workflow_id"] == "workflow.cwl"


def test_workflow_crate_formal_parameters_and_main_entity(
    tmp_path: Path, monkeypatch: object
) -> None:
    import json as _json

    from ro_crate_run.cli import main

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / "Snakefile").write_text("rule all:\n    input: 'out.txt'\n")
    (tmp_path / "in.csv").write_text("a,b\n")
    assert main(["start", "WF", "--profile", "workflow", "--no-checkpoint"]) == 0
    assert main(["input", "Snakefile", "--role", "workflow-definition"]) == 0
    assert main(["input", "in.csv", "--role", "dataset"]) == 0
    assert main(["output", "out.txt", "--role", "result"]) == 0
    (tmp_path / "out.txt").write_text("x\n")
    assert main(["checkpoint", "--profile", "workflow"]) == 0
    graph = _json.loads(
        (tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text()
    )["@graph"]
    by_id = {e["@id"]: e for e in graph}
    root = by_id["./"]
    assert root["mainEntity"] == {"@id": "Snakefile"}
    assert any(e.get("@type") == "FormalParameter" for e in graph)
    workflow = by_id["Snakefile"]
    assert workflow["input"] == [{"@id": by_id["in.csv"]["exampleOfWork"]["@id"]}]
    assert workflow["output"] == [{"@id": by_id["out.txt"]["exampleOfWork"]["@id"]}]
    # in.csv is a declared input that is NOT the workflow def → gets exampleOfWork
    assert "in.csv" in by_id
    assert "exampleOfWork" in by_id["in.csv"]
    # Snakefile is the workflow definition → no exampleOfWork
    assert "exampleOfWork" not in by_id["Snakefile"]
    # programmingLanguage references the engine SoftwareApplication, which is emitted as an
    # entity (not a bare string), so the reference resolves and is not dangling.
    assert workflow["programmingLanguage"] == {"@id": "#actor/engine/snakemake"}
    assert by_id["#actor/engine/snakemake"]["@type"] == "SoftwareApplication"
    assert_no_dangling_refs(graph)
