from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run import commands
from ro_crate_run.constants import EVENT_TYPES
from ro_crate_run.hooks import EVENT_MAP, handle_hook


def _read_events(state_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (state_dir / "events.ndjson").read_text().splitlines()
        if line.strip()
    ]


def test_hook_unknown_registered_in_vocabulary() -> None:
    # L7: the catch-all type must be a registered event type so the L0 vocabulary
    # check accepts it.
    assert "hook.unknown" in EVENT_TYPES


def test_unmapped_event_routes_to_hook_unknown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)

    event_name = "SomeBrandNewLifecycleHook"
    assert event_name not in EVENT_MAP

    result = handle_hook(
        event_name,
        {"cwd": str(tmp_path), "detail": "payload-value"},
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0

    events = _read_events(tmp_path / ".ro-crate-run")
    unknown = [e for e in events if e["event_type"] == "hook.unknown"]
    assert len(unknown) == 1
    appended = unknown[0]

    # The appended event_type is a registered vocabulary type (so L0 won't fail).
    assert appended["event_type"] in EVENT_TYPES
    # The original event name is preserved in the payload.
    assert appended["payload"]["hook_event"] == event_name
    # Original payload fields survive.
    assert appended["payload"]["detail"] == "payload-value"


def test_mapped_event_does_not_use_hook_unknown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)

    # FileChanged is in EVENT_MAP -> file.changed, must NOT become hook.unknown.
    handle_hook(
        "FileChanged",
        {"cwd": str(tmp_path), "path": "x.txt"},
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    events = _read_events(tmp_path / ".ro-crate-run")
    types = {e["event_type"] for e in events}
    assert "file.changed" in types
    assert "hook.unknown" not in types
    # And no payload carries a hook_event marker for the mapped path.
    for e in events:
        if e["event_type"] == "file.changed":
            assert "hook_event" not in e["payload"]


def test_unknown_event_then_checkpoint_does_not_raise_unknown_type(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)

    handle_hook(
        "WildcardHookEvent",
        {"cwd": str(tmp_path)},
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )

    from ro_crate_run.context import ProjectContext
    from ro_crate_run.materialize.builder import checkpoint

    ctx = ProjectContext.from_cwd(str(tmp_path), env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    rc = checkpoint(ctx.state_dir, "process")
    assert rc == 0

    # The L0 validator must not flag an unknown_event_type for our catch-all.
    from ro_crate_run.validation.validator import validate_run

    report = validate_run(ctx.state_dir, public=False, append_event=False)
    codes = {f.code for f in report.errors}
    assert "unknown_event_type" not in codes
