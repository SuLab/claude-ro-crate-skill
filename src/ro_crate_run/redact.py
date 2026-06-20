"""The ``rcr redact`` command: scan a project's captured files and event journal
for secret patterns and, when applied, rewrite them with redacted copies.

The scanning policy is shared with the export-time privacy gate (see
`redaction.scan_file_for_secrets`): files are read losslessly as latin-1 so an
ASCII secret embedded in a binary blob is still caught, and only an unreadable
file (OSError) is skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

from .events import compute_event_hash, dump_event_line
from .journal import EventWriter
from .redaction import Redactor, scan_file_for_secrets
from .state import load_state, read_events, write_state
from .time import utc_now, utc_now_compact


def redact_run(state_dir: Path, *, apply: bool = False, policy: Path | str | None = None) -> int:
    from .state import load_config

    cfg = load_config(state_dir)
    redactor = Redactor.from_config(cfg, state_dir=state_dir)
    if policy:
        redactor.add_patterns_from(Path(policy))
    findings = _scan_files(state_dir, redactor)
    report = {"status": "findings" if findings else "clean", "findings": findings}
    print(json.dumps(report, indent=2, sort_keys=True))
    if not findings:
        return 0
    if not apply:
        return 1
    try:
        _redact_event_journal(state_dir, redactor)
        _redact_text_files(state_dir, redactor)
    except Exception as exc:
        EventWriter(state_dir).append(
            "redaction.failed",
            {"error": str(exc), "finding_count": len(findings)},
            source_kind="materializer",
            redacted=True,
        )
        raise
    EventWriter(state_dir).append(
        "redaction.applied",
        {
            "finding_count": len(findings),
            "redacted_journal": ".ro-crate-run/reports/redacted-events.ndjson",
        },
        source_kind="materializer",
        redacted=True,
    )
    return 0


def _scan_files(state_dir: Path, redactor: Redactor) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in _candidate_files(state_dir):
        if not path.exists() or not path.is_file():
            continue
        if scan_file_for_secrets(path, redactor):
            findings.append({"path": _display_path(state_dir, path), "code": "secret_pattern"})
    return findings


def _redact_text_files(state_dir: Path, redactor: Redactor) -> None:
    for path in _candidate_files(state_dir):
        if path.name == "events.ndjson":
            continue
        if not path.exists() or not path.is_file():
            continue
        # Read losslessly as latin-1 (matching the shared scan policy) so a
        # non-UTF-8 file carrying an ASCII secret is rewritten rather than skipped.
        try:
            text = path.read_bytes().decode("latin-1")
        except OSError:
            continue
        result = redactor.redact_text(text)
        if result.applied:
            path.write_text(result.text, encoding="latin-1")


def _redact_event_journal(state_dir: Path, redactor: Redactor) -> None:
    journal_path = state_dir / "events.ndjson"
    # Rewriting the journal recomputes the entire hash chain, so it must be exclusive
    # with appends and recovery — hold the append lock for the whole read-modify-write.
    with FileLock(str(state_dir / "lock")):
        events = read_events(state_dir)
        if not events:
            return
        backup = state_dir / f"events.ndjson.pre-redaction-{utc_now_compact()}"
        backup.write_text(journal_path.read_text(encoding="utf-8"), encoding="utf-8")
        previous = None
        redacted_events: list[dict[str, Any]] = []
        for sequence, event in enumerate(events, start=1):
            redacted_event = cast(dict[str, Any], redactor.redact_value(event)[0])
            if redacted_event != event:
                redacted_event["redacted"] = True
            redacted_event["sequence"] = sequence
            redacted_event["previous_event_hash"] = previous
            redacted_event["event_hash"] = None
            redacted_event["timestamp"] = redacted_event.get("timestamp") or utc_now()
            redacted_event["event_hash"] = compute_event_hash(redacted_event)
            previous = redacted_event["event_hash"]
            redacted_events.append(redacted_event)
        payload = "".join(dump_event_line(event) for event in redacted_events)
        report_path = state_dir / "reports" / "redacted-events.ndjson"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload, encoding="utf-8")
        # Atomic rewrite (tmp + replace) so a crash mid-write cannot truncate/corrupt the
        # authoritative journal, matching state.py::write_state.
        journal_tmp = journal_path.with_suffix(".ndjson.tmp")
        journal_tmp.write_text(payload, encoding="utf-8")
        journal_tmp.replace(journal_path)
        state = load_state(state_dir)
        state.sequence = int(redacted_events[-1]["sequence"])
        state.last_event_hash = str(redacted_events[-1]["event_hash"])
        state.dirty = True
        write_state(state_dir, state)


def _candidate_files(state_dir: Path) -> list[Path]:
    paths = [state_dir / "events.ndjson"]
    for rel in ["commands", "logs", "ro-crate"]:
        root = state_dir / rel
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    return paths


def _display_path(state_dir: Path, path: Path) -> str:
    try:
        return ".ro-crate-run/" + path.relative_to(state_dir).as_posix()
    except ValueError:
        return str(path)
