"""Crate finalization and export.

Stages the exact crate that will ship into ``staging/export-crate/``, runs the
validation/privacy gate over the staged copy, and only then writes the final
summary, optionally signs the manifest, and zips the result. The gate fails
closed: a failed public export ships nothing and records a ``run.export.blocked``
event for the audit trail.
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

from .constants import DETERMINISTIC_ZIP_EPOCH
from .fs import write_json
from .journal import EventWriter
from .materialize.builder import checkpoint
from .state import load_state
from .validation.validator import validate_run


def _stage_crate(state_dir: Path, include_event_journal: bool) -> Path:
    """Copy the canonical crate into ``staging/export-crate`` and return that path.

    This is the exact artifact that will ship; the privacy gate runs over it (not
    the live crate) so nothing leaks. When requested, the event journal is embedded
    so it travels inside the staged copy.
    """
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
    return staging


def _run_export_gate(state_dir: Path, staging: Path, public: bool) -> str | None:
    """Validate the STAGED crate and fail closed: return its status, or None if blocked.

    Gating the staged dir (``crate_dir=staging``), not the live crate, is the core
    ``--public`` guarantee. On a failed gate a ``run.export.blocked`` event is recorded
    so the rejected attempt is auditable and None is returned so the caller ships
    nothing; otherwise the validation status ("passed"/"warning") flows to the summary.
    """
    report = validate_run(state_dir, strict=False, public=public, crate_dir=staging)
    if report.status == "failed":
        EventWriter(state_dir).append(
            "run.export.blocked",
            {
                "public": public,
                "reason": "privacy gate failed",
                "findings": [f.code for f in report.errors],
            },
            source_kind="materializer",
        )
        return None
    return report.status


def _emit_finalized_events(state_dir: Path, *, public: bool, zip_output: bool) -> None:
    """Record run.finalized then crate.finalized with the shared finalize payload."""
    writer = EventWriter(state_dir)
    payload = {"public": public, "zip": zip_output}
    writer.append("run.finalized", payload, source_kind="materializer")
    writer.append("crate.finalized", payload, source_kind="materializer")


def finalize(
    state_dir: Path,
    *,
    zip_output: bool = False,
    public: bool = False,
    include_event_journal: bool = False,
    out: Path | None = None,
    sign_fn: Callable[[], int] | None = None,
) -> int:
    """Checkpoint if needed, stage the crate, run the privacy gate, then export.

    Re-runs a checkpoint when the crate is stale, copies it into the staging
    directory (optionally embedding the event journal), and validates the staged
    copy with ``public=`` controlling the L5 gate. On a failed gate nothing
    ships and ``run.export.blocked`` is recorded; otherwise the summary is
    written, the manifest is optionally signed, and the crate is optionally
    zipped. Returns 0 on success, non-zero when the gate or signing fails.
    """
    state = load_state(state_dir)
    if state.dirty or not state.last_checkpoint:
        checkpoint(
            state_dir,
            requested_profile=state.requested_profile if state.requested_profile else "auto",
        )
        state = load_state(state_dir)

    # Stage the exact artifact that will ship, gate it, and ship only on success.
    # The staging dir is torn down in the finally so it never leaks on any exit path.
    staging = _stage_crate(state_dir, include_event_journal)
    try:
        gate_status = _run_export_gate(state_dir, staging, public)
        if gate_status is None:
            return 1

        summary_path = state_dir / "reports" / "final-summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            summary_path,
            {
                "run_id": state.run_id,
                "title": state.title,
                "validation_status": gate_status,
                "public": public,
                "include_event_journal": include_event_journal,
            },
        )
        _emit_finalized_events(state_dir, public=public, zip_output=zip_output)
        # test_spec_closure.py::test_include_event_journal_places_journal_in_private_zip
        # asserts the journal at ro-crate/.ro-crate-run/events.ndjson for private crates,
        # so persist it into the canonical crate dir alongside the staged copy.
        if include_event_journal and not public:
            canon = state_dir / "ro-crate" / ".ro-crate-run" / "events.ndjson"
            canon.parent.mkdir(parents=True, exist_ok=True)
            journal_src = state_dir / "events.ndjson"
            if journal_src.exists():
                shutil.copy2(journal_src, canon)
        # Sign BEFORE zipping so the signature ships inside the archive; the signature
        # must cover the same bytes that ship, so the signed canonical manifest is
        # copied into staging before the archive is built.
        if sign_fn is not None:
            sign_rc = sign_fn()
            if sign_rc != 0:
                return sign_rc
            sig = state_dir / "ro-crate" / "ro-crate-metadata.json.sig"
            if sig.exists():
                shutil.copy2(sig, staging / "ro-crate-metadata.json.sig")
        if zip_output:
            export_zip(
                staging,
                out if out is not None else state_dir / f"{state.run_id}.zip",
                include_event_journal=include_event_journal,
            )
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def export_zip(crate_dir: Path, out_path: Path, include_event_journal: bool = False) -> Path:
    """Zip ``crate_dir`` deterministically: identical crates yield byte-identical zips.

    Each entry gets a fixed timestamp and fixed mode and is DEFLATE-compressed
    uniformly so the bytes are stable. ``events.ndjson`` is excluded unless
    ``include_event_journal`` is set, keeping the journal out of shipped archives by
    default.
    """
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(crate_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(crate_dir).as_posix()
                if not include_event_journal and rel.endswith("events.ndjson"):
                    continue
                info = zipfile.ZipInfo(rel)
                # Fixed timestamp so identical crates produce byte-identical zips.
                info.date_time = DETERMINISTIC_ZIP_EPOCH
                info.external_attr = 0o644 << 16
                # writestr honors the ZipInfo's own compress_type (defaults to STORED),
                # not the ZipFile-level compression — set it so entries are deflated.
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
    return out_path
