from __future__ import annotations

from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.inspect import inspect_crate, mermaid_graph


def test_inspect_html_outputs_document(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Render Demo"]) == 0
    assert main(["inspect", "--html"]) == 0
    out = capsys.readouterr().out
    assert "<html" in out.lower()
    assert "Render Demo" in out


def test_graph_has_action_to_output_edges(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Graph", "--no-checkpoint"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('x')",
            ]
        )
        == 0
    )
    assert main(["checkpoint"]) == 0
    graph = mermaid_graph(tmp_path / ".ro-crate-run")
    assert "graph TD" in graph
    assert "-->" in graph
    assert "out.txt" in graph


def test_inspect_crate_without_manifest_returns_clean_message(tmp_path: Path) -> None:
    # No crate has been materialized, so inspect_crate must report gracefully
    # (symmetric with mermaid_graph) rather than raising FileNotFoundError.
    result = inspect_crate(tmp_path / ".ro-crate-run")
    assert result == {"error": "no crate; run rcr checkpoint"}
