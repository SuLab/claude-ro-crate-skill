"""Guard the implicit contract between hooks.json, the dispatch tables, and the
event vocabulary so a new lifecycle event cannot silently drift out of sync.

Adding a Claude lifecycle event touches several hand-maintained structures
(hooks.json x2 copies, EVENT_MAP, _HOOK_HANDLERS, constants.EVENT_TYPES). These
tests turn the "they must agree" expectation into checked assertions: every
hooks.json event routes to a real handler (never silently to hook.unknown), every
mapped journal type is a registered vocabulary type, and the two byte-identical
hooks.json copies stay identical.
"""

from __future__ import annotations

import json
from pathlib import Path

import ro_crate_run
from ro_crate_run.constants import EVENT_TYPES
from ro_crate_run.hooks import _HOOK_HANDLERS, EVENT_MAP

_PACKAGE_ROOT = Path(ro_crate_run.__file__).resolve().parent
_ASSET_HOOKS_JSON = _PACKAGE_ROOT / "assets" / "hooks" / "hooks.json"
_REPO_HOOKS_JSON = _PACKAGE_ROOT.parents[1] / "hooks" / "hooks.json"


def _hooks_json_event_names(path: Path) -> set[str]:
    data = json.loads(path.read_text())
    return set(data["hooks"].keys())


def test_every_hooks_json_event_is_dispatched() -> None:
    # Every event wired up in hooks.json must resolve to either a generic EVENT_MAP
    # entry or a custom handler; otherwise it would silently route to hook.unknown.
    dispatched = set(EVENT_MAP) | set(_HOOK_HANDLERS)
    declared = _hooks_json_event_names(_ASSET_HOOKS_JSON)
    undispatched = declared - dispatched
    assert not undispatched, (
        f"hooks.json events with no EVENT_MAP/_HOOK_HANDLERS entry would route to "
        f"hook.unknown: {sorted(undispatched)}"
    )


def test_every_event_map_target_is_a_registered_event_type() -> None:
    # Every journal event type EVENT_MAP can emit must be in the L0 vocabulary, so a
    # mapped event never fails the unknown_event_type check.
    unregistered = set(EVENT_MAP.values()) - EVENT_TYPES
    assert not unregistered, f"EVENT_MAP targets missing from EVENT_TYPES: {sorted(unregistered)}"


def test_hooks_json_copies_are_byte_identical() -> None:
    # The plugin-root and packaged hooks.json copies have no automated sync; assert
    # they stay byte-identical (skip if the repo-root copy is not present, e.g. an
    # installed-only layout).
    if not _REPO_HOOKS_JSON.exists():
        return
    assert _REPO_HOOKS_JSON.read_bytes() == _ASSET_HOOKS_JSON.read_bytes()
