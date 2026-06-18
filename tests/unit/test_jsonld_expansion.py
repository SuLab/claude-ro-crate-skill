from __future__ import annotations

from ro_crate_run.validation.jsonld import expand_metadata


def test_expands_minimal_crate_offline() -> None:
    metadata = {
        "@context": [
            "https://w3id.org/ro/crate/1.2/context",
            "https://w3id.org/ro/terms/workflow-run/context",
        ],
        "@graph": [
            {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"}},
            {"@id": "./", "@type": "Dataset", "name": "X", "description": "Y"},
        ],
    }
    triples, error = expand_metadata(metadata)
    assert error is None
    assert triples > 0


def test_reports_error_on_broken_jsonld() -> None:
    _triples, error = expand_metadata({"@context": 12345, "@graph": [{"@id": "./"}]})
    assert error is not None
