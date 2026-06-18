from __future__ import annotations

import json
from pathlib import Path

from tests.golden._compare import extract_dimensions, find_secret_leaks


def _write_crate(crate_dir: Path, graph: list[dict]) -> None:
    crate_dir.mkdir(parents=True, exist_ok=True)
    (crate_dir / "ro-crate-metadata.json").write_text(
        json.dumps({"@graph": graph}, indent=2)
    )


def test_extract_dimensions_is_uuid_and_timestamp_stable(tmp_path: Path) -> None:
    graph = [
        {
            "@id": "./",
            "@type": "Dataset",
            "conformsTo": [{"@id": "https://w3id.org/ro/wfrun/process/0.5"}],
            "hasPart": [{"@id": "out.txt"}],
            "mentions": [{"@id": "urn:uuid:AAAA"}],
        },
        {"@id": "out.txt", "@type": "File", "name": "out.txt"},
        {
            "@id": "urn:uuid:AAAA",
            "@type": "CreateAction",
            "name": "Run script",
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
            "instrument": {"@id": "#software/python3"},
            "object": [],
            "result": [{"@id": "out.txt"}],
            "startTime": "2026-06-17T21:30:00Z",
        },
        {"@id": "#software/python3", "@type": "SoftwareApplication", "name": "python3"},
    ]
    crate_a = tmp_path / "a"
    _write_crate(crate_a, graph)

    # same crate, different uuid + timestamp + a re-ordered graph
    graph_b = list(reversed(graph))
    graph_b = json.loads(
        json.dumps(graph_b)
        .replace("urn:uuid:AAAA", "urn:uuid:ZZZZ")
        .replace("21:30:00", "23:59:59")
    )
    crate_b = tmp_path / "b"
    _write_crate(crate_b, graph_b)

    assert extract_dimensions(crate_a) == extract_dimensions(crate_b)
    dims = extract_dimensions(crate_a)
    assert dims["root_conformsTo"] == ["https://w3id.org/ro/wfrun/process/0.5"]
    assert dims["stable_file_ids"] == ["out.txt"]
    assert dims["actions"]["Run script"]["result"] == ["out.txt"]
    assert dims["actions"]["Run script"]["instrument"] == "#software/python3"
    assert dims["entity_types"]["CreateAction"] == 1


def test_find_secret_leaks_detects_literal_and_regex(tmp_path: Path) -> None:
    crate = tmp_path / "ro-crate"
    crate.mkdir()
    (crate / "note.txt").write_text(
        "token=ghp_0123456789012345678901234567890123 secret-prompt"
    )
    leaks = find_secret_leaks(crate, needles=["secret-prompt"])
    joined = " ".join(leaks)
    assert "secret-prompt" in joined
    assert "note.txt" in joined
