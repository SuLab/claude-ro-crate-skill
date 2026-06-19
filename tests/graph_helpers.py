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


def reachable_ids(graph: list[dict[str, Any]]) -> set[str]:
    """Return the set of @ids reachable from the root data entity + descriptor by following
    ``{"@id": ...}`` references. The complement (entities present but unreachable) are
    orphans — discoverable by no consumer walking down from the root."""
    by_id = {str(e.get("@id")): e for e in graph}
    seen: set[str] = set()
    stack = ["./", "ro-crate-metadata.json"]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        stack.extend(_referenced_ids({k: v for k, v in by_id[cur].items() if k != "@id"}))
    return seen


def assert_declared_io_reachable(graph: list[dict[str, Any]]) -> None:
    """Every declared input/output File or Dataset MUST be reachable from the root.

    A declared input/output that exists in the graph but is referenced by nothing is an
    orphan — the user explicitly declared it (rcr input/output) yet it is silently absent
    from the crate's navigable structure, violating "crates must contain all expected
    information". This is a targeted invariant (declared scientific I/O only), not a blanket
    zero-orphan rule: contextual entities like #git/state and unused actors are out of scope.
    """
    reachable = reachable_ids(graph)
    for entity in graph:
        types = entity.get("@type")
        types = types if isinstance(types, list) else [types]
        if not ({"File", "Dataset"} & set(types)):
            continue
        eid = str(entity.get("@id"))
        # Only local declared data files (skip internal sidecars under .ro-crate-run/ and
        # remote/URI references, which have their own linkage rules).
        if eid.startswith((".ro-crate-run/", "http://", "https://", "urn:", "file:", "#")):
            continue
        assert eid in reachable, (
            f"declared data entity {eid!r} is an orphan — present in @graph but unreachable "
            f"from the root './' (no hasPart/mentions/object/result reference)"
        )
