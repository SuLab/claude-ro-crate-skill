"""Guard tests for the byte-identical duplicated-asset invariant (audit C1).

CLAUDE.md and docs/audit/CONTRACT.md require the plugin-root ``hooks/``,
``skills/`` and ``templates/`` trees to stay byte-identical to their packaged
copies under ``src/ro_crate_run/assets/`` (the packaged copies are what
``rcr install-project`` vendors), and every ``_bootstrap.py`` / ``hooks.json``
copy in the repo to match the others. There is no automated sync, so these
tests fail the moment one side drifts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Directories/files inside the asset trees that are build artifacts, not source,
# and therefore must not be compared.
_IGNORED_DIRS = {"__pycache__"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}

# (plugin-root tree, packaged copy under src/ro_crate_run/assets/)
_TREE_PAIRS = (
    ("hooks", "src/ro_crate_run/assets/hooks"),
    ("skills", "src/ro_crate_run/assets/skills"),
    ("templates", "src/ro_crate_run/assets/templates"),
)


def _iter_files(root: Path) -> dict[str, bytes]:
    """Map every non-artifact file under ``root`` to its bytes, keyed by the
    path relative to ``root`` (POSIX form, for cross-tree comparison)."""
    out: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix in _IGNORED_SUFFIXES:
            continue
        out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


@pytest.mark.parametrize("plugin_rel,packaged_rel", _TREE_PAIRS)
def test_asset_tree_is_byte_identical(
    repo_root: Path, plugin_rel: str, packaged_rel: str
) -> None:
    plugin_dir = repo_root / plugin_rel
    packaged_dir = repo_root / packaged_rel
    assert plugin_dir.is_dir(), f"missing plugin-root tree: {plugin_rel}"
    assert packaged_dir.is_dir(), f"missing packaged tree: {packaged_rel}"

    plugin_files = _iter_files(plugin_dir)
    packaged_files = _iter_files(packaged_dir)

    plugin_only = sorted(set(plugin_files) - set(packaged_files))
    packaged_only = sorted(set(packaged_files) - set(plugin_files))
    assert plugin_only == [], (
        f"files only under {plugin_rel} (not vendored into {packaged_rel}): {plugin_only}"
    )
    assert packaged_only == [], (
        f"files only under {packaged_rel} (not in plugin-root {plugin_rel}): {packaged_only}"
    )

    differing = sorted(
        rel for rel, data in plugin_files.items() if packaged_files[rel] != data
    )
    assert differing == [], (
        f"byte mismatch between {plugin_rel}/ and {packaged_rel}/: {differing}"
    )


def _bootstrap_copies(repo_root: Path) -> list[Path]:
    copies = sorted(repo_root.rglob("_bootstrap.py"))
    # Exclude anything inside a vendored/installed lib or build artifact dir.
    return [
        p
        for p in copies
        if not any(part in {"__pycache__", ".claude", "build", "dist"} for part in p.parts)
    ]


def test_all_bootstrap_copies_are_byte_identical(repo_root: Path) -> None:
    copies = _bootstrap_copies(repo_root)
    # The duplication is structural (each sibling-import context needs its own
    # copy): plugin hooks/, plugin skills scripts/, and both packaged mirrors.
    assert len(copies) >= 4, f"expected >=4 _bootstrap.py copies, found: {copies}"

    reference = copies[0]
    reference_bytes = reference.read_bytes()
    mismatched = sorted(
        str(p.relative_to(repo_root))
        for p in copies[1:]
        if p.read_bytes() != reference_bytes
    )
    assert mismatched == [], (
        f"_bootstrap.py copies drifted from {reference.relative_to(repo_root)}: {mismatched}"
    )


def test_hooks_json_copies_are_byte_identical(repo_root: Path) -> None:
    plugin_hooks_json = repo_root / "hooks" / "hooks.json"
    packaged_hooks_json = repo_root / "src" / "ro_crate_run" / "assets" / "hooks" / "hooks.json"
    assert plugin_hooks_json.is_file()
    assert packaged_hooks_json.is_file()
    assert plugin_hooks_json.read_bytes() == packaged_hooks_json.read_bytes(), (
        "hooks/hooks.json and src/ro_crate_run/assets/hooks/hooks.json have drifted"
    )
