"""CLI creation paths for ParameterConnection and ContainerImage (previously unreachable)."""
from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.commands import _parse_image_ref


def _events(state_dir: Path) -> list[dict]:
    text = (state_dir / "events.ndjson").read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_parameter_connection_recorded_in_event(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "T", "--mode", "advisory", "--profile", "workflow", "--no-checkpoint"]) == 0
    assert main(["parameter", "inB", "v", "--connect-from", "#param/a", "--connect-to", "#param/b"]) == 0
    ev = [e for e in _events(tmp_path / ".ro-crate-run")
          if e["event_type"] == "workflow.parameter.declared"][-1]
    assert ev["payload"]["connection"] == {"source": "#param/a", "target": "#param/b"}


def test_parameter_without_both_connect_flags_has_no_connection(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "T", "--mode", "advisory", "--profile", "workflow", "--no-checkpoint"]) == 0
    assert main(["parameter", "x", "v", "--connect-from", "#param/a"]) == 0
    ev = [e for e in _events(tmp_path / ".ro-crate-run")
          if e["event_type"] == "workflow.parameter.declared"][-1]
    assert "connection" not in ev["payload"]


def test_container_command_records_observed_event(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "T", "--mode", "advisory", "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["container", "ghcr.io/org/img:1.2", "--digest", "sha256:deadbeef"]) == 0
    ev = [e for e in _events(tmp_path / ".ro-crate-run")
          if e["event_type"] == "container.observed"][-1]
    p = ev["payload"]
    assert (p["registry"], p["image"], p["tag"], p["digest"]) == (
        "ghcr.io", "org/img", "1.2", "sha256:deadbeef")


def test_parse_image_ref_variants() -> None:
    assert _parse_image_ref("python:3.12") == ("", "python", "3.12", "")
    assert _parse_image_ref("docker.io/library/python:3.12") == (
        "docker.io", "library/python", "3.12", "")
    assert _parse_image_ref("img@sha256:abc") == ("", "img", "", "sha256:abc")
    assert _parse_image_ref("localhost:5000/img:tag") == ("localhost:5000", "img", "tag", "")
    assert _parse_image_ref("alpine") == ("", "alpine", "", "")
