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

from .clock import utc_now, utc_now_compact
from .events import dump_event_line, event_from_dict, event_to_dict
from .journal import EventWriter
from .models import RcrEvent
from .redaction import Redactor, iter_regular_files, scan_file_for_secrets
from .state import read_events


def redact_run(state_dir: Path, *, apply: bool = False, policy: Path | str | None = None) -> int:
    """Scan the project for secrets and, with ``apply``, rewrite them out.

    Always scans the candidate files (journal + captured commands/logs/crate),
    prints a JSON report, and returns:

    - ``0`` when nothing matches (status ``clean``);
    - ``1`` when secrets are found but ``apply`` is ``False`` (report only);
    - ``0`` after a successful ``apply`` that redacts the journal and text files.

    Applying re-links the whole event chain (via :meth:`EventWriter.rewrite_chain`)
    and emits ``redaction.applied`` (or ``redaction.failed`` if a rewrite raises,
    which is then re-raised). ``policy`` adds extra patterns from a JSON file.
    """
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
    """Redact every journaled event and re-link the whole chain.

    Reads the journal, masks each event's secrets, flags changed events
    ``redacted``, then hands the events to :meth:`EventWriter.rewrite_chain`,
    which owns the lock, atomic rewrite, hash re-linking, and state bump. The
    pre-redaction journal is preserved as a timestamped backup, and the final
    re-linked chain is also dropped into ``reports/redacted-events.ndjson``.
    """
    journal_path = state_dir / "events.ndjson"
    raw_events = read_events(state_dir)
    if not raw_events:
        return
    backup = state_dir / f"events.ndjson.pre-redaction-{utc_now_compact()}"
    backup.write_text(journal_path.read_text(encoding="utf-8"), encoding="utf-8")
    events: list[RcrEvent] = []
    for sequence, raw in enumerate(raw_events, start=1):
        redacted = cast(dict[str, Any], redactor.redact_value(raw)[0])
        if redacted != raw:
            redacted["redacted"] = True
        redacted["sequence"] = sequence
        # Defensive: a missing/blank timestamp would break event reconstruction;
        # stored events always carry one, but never persist a null.
        redacted["timestamp"] = redacted.get("timestamp") or utc_now()
        events.append(event_from_dict(redacted))
    # rewrite_chain re-links previous/event hashes in place under the append lock,
    # atomically rewrites the journal, and bumps derived state (dirty stays True
    # because the chain's final event maps to dirty_effect "set").
    EventWriter(state_dir).rewrite_chain(events)
    # Mirror the now-re-linked chain into the reports dir for inspection.
    report_path = state_dir / "reports" / "redacted-events.ndjson"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "".join(dump_event_line(event_to_dict(event)) for event in events),
        encoding="utf-8",
    )


def _candidate_files(state_dir: Path) -> list[Path]:
    paths = [state_dir / "events.ndjson"]
    for rel in ["commands", "logs", "ro-crate"]:
        root = state_dir / rel
        if root.exists():
            paths.extend(iter_regular_files(root))
    return paths


def _display_path(state_dir: Path, path: Path) -> str:
    try:
        return ".ro-crate-run/" + path.relative_to(state_dir).as_posix()
    except ValueError:
        return str(path)
