from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.adapters.imports import import_existing_ro_crate


def test_import_extracts_actions_steps_params_files(tmp_path: Path) -> None:
    graph = [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork"},
        {"@id": "./", "@type": "Dataset"},
        {
            "@id": "wf.cwl",
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
            "name": "wf.cwl",
        },
        {
            "@id": "urn:uuid:1",
            "@type": "CreateAction",
            "name": "run",
            "instrument": {"@id": "wf.cwl"},
        },
        {"@id": "#step/normalize", "@type": "HowToStep", "name": "normalize"},
        {"@id": "#param/threshold", "@type": "FormalParameter", "name": "threshold"},
        {"@id": "results/out.csv", "@type": "File", "name": "out.csv"},
    ]
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps({"@graph": graph}))
    events = import_existing_ro_crate(tmp_path)
    types = {e["event_type"] for e in events}
    assert "workflow.identified" in types
    assert "execution.command.completed" in types
    assert "workflow.step.identified" in types
    assert "workflow.parameter.declared" in types
    assert "file.observed" in types
