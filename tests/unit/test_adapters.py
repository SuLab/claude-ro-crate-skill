from __future__ import annotations

from pathlib import Path

from ro_crate_run import adapters
from ro_crate_run.materialize import profiles
from ro_crate_run.models import RunModel


def test_detect_snakemake_with_steps(tmp_path: Path) -> None:
    snake = tmp_path / "Snakefile"
    snake.write_text("rule normalize:\n    shell: 'x'\nrule report:\n    shell: 'y'\n")
    result = adapters.detect_engine(snake)
    assert result is not None
    assert result["engine"] == "snakemake"
    assert result["steps"] == ["normalize", "report"]


def test_detect_cwl(tmp_path: Path) -> None:
    wf = tmp_path / "workflow.cwl"
    wf.write_text("cwlVersion: v1.2\nclass: Workflow\n")
    result = adapters.detect_engine(wf)
    assert result is not None and result["engine"] == "cwl"


def test_detect_nextflow(tmp_path: Path) -> None:
    wf = tmp_path / "main.nf"
    wf.write_text("process FOO { script: 'echo hi' }\n")
    result = adapters.detect_engine(wf)
    assert result is not None
    assert result["engine"] == "nextflow"


def test_detect_galaxy(tmp_path: Path) -> None:
    wf = tmp_path / "workflow.ga"
    wf.write_text('{"a_galaxy_workflow": "true", "steps": {}}\n')
    result = adapters.detect_engine(wf)
    assert result is not None
    assert result["engine"] == "galaxy"


def test_detect_none(tmp_path: Path) -> None:
    plain = tmp_path / "script.py"
    plain.write_text("print('hi')\n")
    assert adapters.detect_engine(plain) is None


def _model_with_workflow(path: str) -> RunModel:
    model = RunModel(
        run_id="run_x",
        title="t",
        description="d",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
        selected_profile="process",
        requested_profile="auto",
        profile_uri="https://w3id.org/ro/wfrun/process/0.5",
        mode="monitored",
        events=[],
    )
    model.workflow = {"path": path, "name": Path(path).name, "engine": "unknown"}
    return model


def test_enrich_sets_engine_and_steps(tmp_path: Path) -> None:
    snake = tmp_path / "Snakefile"
    snake.write_text("rule a:\n    shell: 'x'\nrule b:\n    shell: 'y'\n")
    model = _model_with_workflow(str(snake))
    profiles.enrich_with_adapter(model, tmp_path)
    assert model.workflow["engine"] == "snakemake"
    assert "a" in model.steps and "b" in model.steps


def test_checkpoint_runs_adapter_enrichment(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: the adapter actually runs during `rcr checkpoint` (F5 wiring),
    materializing workflow-file rules as HowToStep without promoting to provenance."""
    import json

    from ro_crate_run.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "Snakefile").write_text(
        "rule normalize:\n    shell: 'x'\nrule report:\n    shell: 'y'\n"
    )
    assert main(["start", "wf", "--no-checkpoint"]) == 0
    assert main(["input", "Snakefile", "--role", "workflow-definition"]) == 0
    assert main(["checkpoint"]) == 0
    meta = json.loads(
        (tmp_path / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json").read_text()
    )

    def _types(entity: dict) -> list:  # type: ignore[type-arg]
        t = entity.get("@type")
        return t if isinstance(t, list) else [t]

    step_names = {e.get("name") for e in meta["@graph"] if "HowToStep" in _types(e)}
    assert {"normalize", "report"} <= step_names  # adapter extracted + materialized rules
    root = next(e for e in meta["@graph"] if e.get("@id") == "./")
    conforms = json.dumps(root.get("conformsTo"))
    assert "workflow/0.5" in conforms and "provenance/0.5" not in conforms
