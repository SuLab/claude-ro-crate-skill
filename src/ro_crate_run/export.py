from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from .journal import EventWriter
from .materialize.builder import checkpoint
from .state import load_state
from .validation.validator import validate_run


def finalize(
    state_dir: Path,
    *,
    zip_output: bool = False,
    public: bool = False,
    include_event_journal: bool = False,
    out: Path | None = None,
) -> int:
    state = load_state(state_dir)
    if state.dirty or not state.last_checkpoint:
        checkpoint(
            state_dir,
            requested_profile=state.requested_profile if state.requested_profile else "auto",
        )
        state = load_state(state_dir)

    # Stage the exact artifact that will ship, THEN gate it.
    staging = state_dir / "staging" / "export-crate"
    staging.parent.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(state_dir / "ro-crate", staging)
    if include_event_journal:
        journal_src = state_dir / "events.ndjson"
        if journal_src.exists():
            journal_dst = staging / ".ro-crate-run" / "events.ndjson"
            journal_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(journal_src, journal_dst)

    report = validate_run(state_dir, strict=False, public=public, crate_dir=staging)
    if report.status == "failed":
        shutil.rmtree(staging, ignore_errors=True)
        # Record the blocked attempt for the audit trail (SPEC §13.4); the gate fails
        # closed, so nothing is shipped.
        EventWriter(state_dir).append(
            "run.export.blocked",
            {
                "public": public,
                "reason": "privacy gate failed",
                "findings": [f.code for f in report.errors],
            },
            source_kind="materializer",
        )
        return 1

    summary_path = state_dir / "reports" / "final-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "run_id": state.run_id,
                "title": state.title,
                "validation_status": report.status,
                "public": public,
                "include_event_journal": include_event_journal,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    EventWriter(state_dir).append(
        "run.finalized", {"public": public, "zip": zip_output}, source_kind="materializer"
    )
    EventWriter(state_dir).append(
        "crate.finalized", {"public": public, "zip": zip_output}, source_kind="materializer"
    )
    # For private crates, persist the journal into the canonical crate dir (back-compat).
    if include_event_journal and not public:
        canon = state_dir / "ro-crate" / ".ro-crate-run" / "events.ndjson"
        canon.parent.mkdir(parents=True, exist_ok=True)
        journal_src = state_dir / "events.ndjson"
        if journal_src.exists():
            shutil.copy2(journal_src, canon)
    if zip_output:
        export_zip(
            staging,
            out if out is not None else state_dir / f"{state.run_id}.zip",
            include_event_journal=include_event_journal,
        )
    shutil.rmtree(staging, ignore_errors=True)
    return 0


def export_zip(crate_dir: Path, out_path: Path, include_event_journal: bool = False) -> Path:
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(crate_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(crate_dir).as_posix()
                if not include_event_journal and rel.endswith("events.ndjson"):
                    continue
                info = zipfile.ZipInfo(rel)
                info.date_time = (2026, 6, 17, 0, 0, 0)
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    return out_path
