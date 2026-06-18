from __future__ import annotations

import pytest

from tests.graph_helpers import assert_no_dangling_refs


def test_passes_when_all_refs_resolve() -> None:
    graph = [{"@id": "a", "x": {"@id": "b"}}, {"@id": "b"}]
    assert_no_dangling_refs(graph)


def test_allows_external_schema_org() -> None:
    assert_no_dangling_refs(
        [{"@id": "a", "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"}}]
    )


def test_raises_on_dangling() -> None:
    with pytest.raises(AssertionError, match="Dangling reference 'missing'"):
        assert_no_dangling_refs([{"@id": "a", "x": {"@id": "missing"}}])
