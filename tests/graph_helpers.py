from __future__ import annotations

from typing import Any

# References that are allowed to point outside the @graph (vocabulary / spec / license / status).
_ALLOWED_EXTERNAL_PREFIXES = (
    "http://schema.org/",
    "https://schema.org/",
    "https://w3id.org/ro/crate/",
    "https://w3id.org/ro/wfrun/",
    "https://w3id.org/ro/terms/",
    "https://creativecommons.org/",
    "https://spdx.org/",
)


def _referenced_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "@id" and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_referenced_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_referenced_ids(item))
    return found


def assert_no_dangling_refs(graph: list[dict[str, Any]]) -> None:
    """Raise AssertionError if any nested ``{"@id": X}`` reference points to an ``@id``
    not present as a top-level graph entity, excluding allowed external URIs."""
    defined = {str(entity.get("@id")) for entity in graph}
    for entity in graph:
        entity_id = str(entity.get("@id"))
        for key, value in entity.items():
            if key == "@id":
                continue
            for ref in _referenced_ids(value):
                if ref in defined:
                    continue
                if ref.startswith(_ALLOWED_EXTERNAL_PREFIXES):
                    continue
                raise AssertionError(
                    f"Dangling reference {ref!r} from entity {entity_id!r} property {key!r}"
                )
