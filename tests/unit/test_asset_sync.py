"""Guard tests for the byte-identical duplicated-asset invariant.

The plugin layout at the repo root (``hooks/``, ``skills/``, ``templates/``)
and the packaged copy under ``src/ro_crate_run/assets/`` (what
``rcr install-project`` vendors) are maintained as byte-identical duplicates
with no automated sync — the CLAUDE.md sync table is the published source of
truth for which trees must match. The load-bearing ``.claude-plugin/plugin.json``
(probed to detect a plugin root) is likewise duplicated and guarded as a pair;
its sibling ``marketplace.json`` is repo-root only and not vendored, so the
guard targets that one file rather than the whole ``.claude-plugin/`` tree.
These tests fail the moment one side drifts: differing bytes, a missing/added
file, a lost executable bit on a launcher Claude invokes directly, or a
stray/relocated ``_bootstrap.py`` shim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run.install import _is_executable_asset

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

# The exact set of legitimate _bootstrap.py homes (one per sibling-import
# context): plugin hooks/, plugin skills scripts/, and both packaged mirrors.
# Pinned as an exact set so a fifth stray copy or a moved/deleted one is caught.
_EXPECTED_BOOTSTRAP_COPIES = frozenset(
    {
        "hooks/_bootstrap.py",
        "skills/ro-crate-run/scripts/_bootstrap.py",
        "src/ro_crate_run/assets/hooks/_bootstrap.py",
        "src/ro_crate_run/assets/skills/ro-crate-run/scripts/_bootstrap.py",
    }
)


def _iter_files(root: Path) -> dict[str, Path]:
    """Map every non-artifact file under ``root`` to its path, keyed by the
    path relative to ``root`` (POSIX form, for cross-tree comparison)."""
    out: dict[str, Path] = {}
    for path in root.rglob("*"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix in _IGNORED_SUFFIXES:
            continue
        out[path.relative_to(root).as_posix()] = path
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
        rel
        for rel, path in plugin_files.items()
        if packaged_files[rel].read_bytes() != path.read_bytes()
    )
    assert differing == [], (
        f"byte mismatch between {plugin_rel}/ and {packaged_rel}/: {differing}"
    )

    # Launchers Claude invokes directly (the rcr script, *.py wrappers/hooks)
    # silently fail to execute if a copy loses its +x bit, yet byte-identity
    # still passes — so assert the owner-execute bit matches across the pair.
    exec_drift = sorted(
        rel
        for rel, path in plugin_files.items()
        if _is_executable_asset(path.name)
        and bool(path.stat().st_mode & 0o111)
        != bool(packaged_files[rel].stat().st_mode & 0o111)
    )
    assert exec_drift == [], (
        f"executable-bit mismatch between {plugin_rel}/ and {packaged_rel}/: {exec_drift}"
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
    found = {p.relative_to(repo_root).as_posix() for p in copies}
    assert found == set(_EXPECTED_BOOTSTRAP_COPIES), (
        "unexpected _bootstrap.py layout "
        f"(missing: {sorted(set(_EXPECTED_BOOTSTRAP_COPIES) - found)}, "
        f"unexpected: {sorted(found - set(_EXPECTED_BOOTSTRAP_COPIES))})"
    )

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


def test_plugin_json_copies_are_byte_identical(repo_root: Path) -> None:
    plugin_json = repo_root / ".claude-plugin" / "plugin.json"
    packaged_json = repo_root / "src" / "ro_crate_run" / "assets" / ".claude-plugin" / "plugin.json"
    assert plugin_json.is_file()
    assert packaged_json.is_file()
    assert plugin_json.read_bytes() == packaged_json.read_bytes(), (
        ".claude-plugin/plugin.json and "
        "src/ro_crate_run/assets/.claude-plugin/plugin.json have drifted"
    )


def test_hooks_json_copies_are_byte_identical(repo_root: Path) -> None:
    plugin_hooks_json = repo_root / "hooks" / "hooks.json"
    packaged_hooks_json = repo_root / "src" / "ro_crate_run" / "assets" / "hooks" / "hooks.json"
    assert plugin_hooks_json.is_file()
    assert packaged_hooks_json.is_file()
    assert plugin_hooks_json.read_bytes() == packaged_hooks_json.read_bytes(), (
        "hooks/hooks.json and src/ro_crate_run/assets/hooks/hooks.json have drifted"
    )
