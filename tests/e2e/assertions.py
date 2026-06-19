from __future__ import annotations

import sys
from pathlib import Path

# Make repo-root test helpers importable (tests/graph_helpers.py, tests/golden/_compare.py)
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tests.e2e.spec import ScenarioResult  # noqa: E402
from tests.golden._compare import find_secret_leaks  # noqa: E402
from tests.graph_helpers import assert_no_dangling_refs  # noqa: E402

RO_CRATE_DESCRIPTOR_CONFORMS = "https://w3id.org/ro/crate/1.2"


def entities_by_id(graph: list) -> dict:
    return {e["@id"]: e for e in graph if "@id" in e}


def _types(entity: dict) -> list:
    t = entity.get("@type", [])
    return t if isinstance(t, list) else [t]


def by_type(graph: list, t: str) -> list:
    return [e for e in graph if t in _types(e)]


def _conforms_ids(value: object) -> list:
    if isinstance(value, dict):
        return [value.get("@id")]
    if isinstance(value, list):
        return [c.get("@id") for c in value if isinstance(c, dict)]
    return []


def assert_descriptor(graph: list) -> None:
    ents = entities_by_id(graph)
    desc = ents.get("ro-crate-metadata.json")
    assert desc is not None, "missing metadata descriptor entity"
    ids = _conforms_ids(desc.get("conformsTo"))
    assert RO_CRATE_DESCRIPTOR_CONFORMS in ids, \
        f"descriptor conformsTo missing {RO_CRATE_DESCRIPTOR_CONFORMS}: {ids}"
    root = ents.get("./")
    assert root is not None, "missing root data entity './'"
    for prop in ("name", "description", "datePublished", "license"):
        assert prop in root, f"root entity missing required property {prop!r}"


def assert_profile(graph: list, uri: str) -> None:
    root = entities_by_id(graph).get("./", {})
    ids = _conforms_ids(root.get("conformsTo", []))
    assert uri in ids, f"root conformsTo {ids} does not include expected profile {uri}"


def assert_entity_type(graph: list, t: str, *, min_count: int = 1) -> None:
    n = len(by_type(graph, t))
    assert n >= min_count, f"expected >={min_count} {t!r} entities, found {n}"


def assert_property(entity: dict, prop: str, *, equals: object = None,
                    contains: object = None) -> None:
    assert prop in entity, f"entity {entity.get('@id')!r} missing property {prop!r}"
    val = entity[prop]
    if equals is not None:
        assert val == equals, f"{prop!r}={val!r} != {equals!r}"
    if contains is not None:
        seq = val if isinstance(val, list) else [val]
        assert contains in seq, f"{contains!r} not in {prop!r}={seq!r}"


def assert_valid(result: ScenarioResult, *, statuses: tuple = ("passed", "warning")) -> None:
    vj = result.validate_json
    assert vj is not None, \
        f"no validate JSON (claude_exit={result.claude_exit})\n{result.transcript[-2000:]}"
    assert vj["errors"] == [], f"validation errors: {vj['errors']}"
    assert vj["status"] in statuses, f"status {vj['status']!r} not in {statuses}"


def assert_no_secret_leaks(result: ScenarioResult, needles: tuple) -> None:
    assert result.crate_path is not None, "no crate to scan"
    leaks = find_secret_leaks(result.crate_path.parent, list(needles))
    assert leaks == [], f"public crate leaked: {leaks}"


def assert_crate(result: ScenarioResult) -> None:
    """Standard per-crate validation battery from the design spec."""
    spec = result.spec
    assert not result.source_tampered, (
        "agent edited the source snapshot under test (the code that produced this crate); "
        "results are untrustworthy"
    )
    if spec.skip_crate_battery:
        if spec.check:
            spec.check(result.graph or [], result)
        return
    assert result.graph is not None, \
        f"no crate emitted (claude_exit={result.claude_exit})\n{result.transcript[-2000:]}"
    assert_no_dangling_refs(result.graph)
    assert_descriptor(result.graph)
    assert_valid(result, statuses=spec.expect_validation_status)
    if spec.expected_profile_uri:
        assert_profile(result.graph, spec.expected_profile_uri)
    if spec.public:
        assert_no_secret_leaks(result, spec.needles)
    if spec.check:
        spec.check(result.graph, result)
