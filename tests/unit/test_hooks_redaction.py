from __future__ import annotations

import json
from pathlib import Path

import pytest

from ro_crate_run import commands
from ro_crate_run.hooks import _is_substantive_raw, handle_hook


def _read_events(state_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (state_dir / "events.ndjson").read_text().splitlines()
        if line.strip()
    ]


def test_hook_payload_is_redacted_after_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # handle_hook passes the raw payload to EventWriter.append, which redacts before
    # persistence. A secret in a tool.completed payload must not survive to the journal.
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)

    secret = "AKIAIOSFODNN7EXAMPLE"
    result = handle_hook(
        "PostToolUse",
        {
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {"command": f"echo {secret}"},
        },
        env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0

    raw = (tmp_path / ".ro-crate-run" / "events.ndjson").read_text()
    assert secret not in raw
    completed = [e for e in _read_events(tmp_path / ".ro-crate-run")
                 if e["event_type"] == "tool.completed"]
    assert completed
    assert secret not in json.dumps(completed[-1])


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("", False),
        ("   ", False),
        ("pwd", False),
        ("ls -la", False),
        ("git status", False),
        ("git rev-parse HEAD", False),
        ("cat file.txt", False),
        ("rcr status", False),
        ("python3 hooks/rocrate_stop.py", False),
        ("python3 -m rcr run -- echo hi", False),
        ("python3 train.py", True),
        ("make build", True),
        ("rm -rf data", True),
    ],
)
def test_is_substantive_raw_table(command: str, expected: bool) -> None:
    assert _is_substantive_raw(command) is expected
