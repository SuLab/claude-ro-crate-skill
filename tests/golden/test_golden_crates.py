from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.golden._compare import assert_matches_golden
from tests.golden._fixtures import FIXTURES


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_golden_crate(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    crate_dir = FIXTURES[name](tmp_path)
    assert (crate_dir / "ro-crate-metadata.json").exists()
    assert_matches_golden(name, crate_dir)


def _all_referenced_ids(meta: dict) -> set[str]:
    refs: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if set(value.keys()) == {"@id"}:
                refs.add(str(value["@id"]))
            else:
                for v in value.values():
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(meta.get("@graph", []))
    return refs


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_golden_crate_has_no_dangling_references(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    crate_dir = FIXTURES[name](tmp_path)
    meta = json.loads((crate_dir / "ro-crate-metadata.json").read_text())
    defined = {str(e.get("@id")) for e in meta["@graph"]}
    referenced = _all_referenced_ids(meta)
    # external (http/urn) targets are allowed; check local fragment/relative ids only
    local = {
        r
        for r in referenced
        if r.startswith(("#", "./")) or ("/" in r and not r.startswith("http"))
    }
    missing = sorted(local - defined)
    assert missing == [], f"{name}: dangling @id references: {missing}"
