"""Validation level 5: the public-export privacy gate.

Scans a staged crate directory and its projected metadata for anything that must
not leave the project — secrets, the raw event journal, raw human prompts,
source code, git diffs, oversized logs, and environment variables outside the
allowlist. Every finding at this level is an error: the gate fails closed so a
public export ships nothing until the crate is clean.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..constants import BYTES_PER_MB
from ..models import PrivacyFinding, ValidationFinding
from ..redaction import Redactor, scan_file_for_secrets
from ..state import read_events_safe
from .context import ValidationContext


def _finding(code: str, message: str, path: str = "") -> ValidationFinding:
    """Construct an L5 (``privacy``) finding; the level is bound here so it is not
    repeated on every emission. Every privacy finding is an error — the export
    gate fails closed — so the default ``severity`` applies."""
    return ValidationFinding("privacy", code, message, path)


def check_public_export_payload(
    payload: Any, include_prompts: bool = False, redactor: Redactor | None = None
) -> list[PrivacyFinding]:
    """Scan an in-memory crate-metadata payload for prompts and secret patterns.

    ``redactor`` lets a caller pass a config-derived redactor so the metadata
    scan honors the same custom patterns as the on-disk file scan; it defaults
    to the built-in pattern set.
    """
    findings: list[PrivacyFinding] = []
    _scan(payload, "", include_prompts, findings, redactor or Redactor.default())
    return findings


def _scan(
    value: Any,
    path: str,
    include_prompts: bool,
    findings: list[PrivacyFinding],
    redactor: Redactor,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if "prompt" in str(key).lower() and not include_prompts:
                findings.append(PrivacyFinding("error", "raw_prompt_in_public_export"))
            _scan(item, child, include_prompts, findings, redactor)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _scan(item, f"{path}[{idx}]", include_prompts, findings, redactor)
    elif isinstance(value, str):
        if redactor.redact_text(value).applied:
            findings.append(PrivacyFinding("error", "secret_pattern", path))


def scan_crate_secrets(crate_dir: Path, redactor: Redactor) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for path in sorted(crate_dir.rglob("*")):
        if not path.is_file():
            continue
        # An ASCII secret can hide inside an otherwise-binary blob; the shared
        # scanner decodes losslessly as latin-1 and skips only files that cannot
        # be read at all, so a non-UTF-8 file never makes the gate fail open.
        if scan_file_for_secrets(path, redactor):
            rel = path.relative_to(crate_dir).as_posix()
            findings.append(_finding("secret_pattern", f"Secret pattern found in {rel}", rel))
    return findings


def journal_findings(
    crate_dir: Path, *, include_event_journal: bool, include_prompts: bool
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for journal in sorted(crate_dir.rglob("events.ndjson")):
        rel = journal.relative_to(crate_dir).as_posix()
        if not include_event_journal:
            findings.append(
                _finding(
                    "event_journal_in_public_export",
                    f"Event journal present in public crate without include_event_journal: {rel}",
                    rel,
                )
            )
        if not include_prompts and _journal_has_prompt(journal):
            findings.append(
                _finding(
                    "raw_prompt_in_public_export",
                    f"Raw prompt present in public crate without include_prompts: {rel}",
                    rel,
                )
            )
    return findings


def _journal_has_prompt(journal: Path) -> bool:
    try:
        events, _ = read_events_safe(journal.parent)
    except (UnicodeDecodeError, OSError):
        return False
    return any(
        isinstance(event, dict) and event.get("event_type") == "human.prompt" for event in events
    )


def source_diff_findings(
    crate_dir: Path,
    *,
    source_roots: list[str],
    include_source_code_public: bool,
    include_git_diff_public: bool,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    roots = [root.rstrip("/") for root in source_roots]
    for path in sorted(crate_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(crate_dir).as_posix()
        name = path.name
        is_diff = name.endswith((".diff", ".patch")) or "git-diff" in name
        if is_diff:
            if not include_git_diff_public:
                findings.append(
                    _finding(
                        "git_diff_in_public_export",
                        f"Git diff included without include_git_diff_public: {rel}",
                        rel,
                    )
                )
            continue
        if rel.startswith(".ro-crate-run/"):
            continue
        if not include_source_code_public and any(
            rel == root or rel.startswith(root + "/") for root in roots
        ):
            findings.append(
                _finding(
                    "source_code_in_public_export",
                    f"Source code included without include_source_code_public: {rel}",
                    rel,
                )
            )
    return findings


def env_findings(crate_dir: Path, *, allowlist: list[str]) -> list[ValidationFinding]:
    allowed = set(allowlist)
    findings: list[ValidationFinding] = []
    for sidecar in sorted(crate_dir.rglob("commands/*.json")):
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        environment = data.get("environment") if isinstance(data, dict) else None
        if not isinstance(environment, dict):
            continue
        rel = sidecar.relative_to(crate_dir).as_posix()
        for key in sorted(environment):
            if key not in allowed:
                findings.append(
                    _finding(
                        "env_var_outside_allowlist",
                        f"Environment variable outside allowlist in public crate: {key}",
                        f"{rel}::{key}",
                    )
                )
    return findings


def log_findings(
    crate_dir: Path, *, include_full_logs: bool, max_log_size_mb: int
) -> list[ValidationFinding]:
    if include_full_logs:
        return []
    limit = max_log_size_mb * BYTES_PER_MB
    findings: list[ValidationFinding] = []
    for log in sorted(crate_dir.rglob("logs/*.txt")):
        if log.is_file() and log.stat().st_size > limit:
            rel = log.relative_to(crate_dir).as_posix()
            findings.append(
                _finding(
                    "full_log_in_public_export",
                    f"Oversized log in public crate without include_full_logs: {rel}",
                    rel,
                )
            )
    return findings


def public_export_findings(ctx: ValidationContext) -> list[ValidationFinding]:
    crate_dir: Path = ctx.crate_dir if ctx.crate_dir is not None else ctx.state_dir / "ro-crate"
    cfg = ctx.cfg
    # Build the redactor from the context's config (the production invariant is
    # that it equals the on-disk config), resolving any relative custom-patterns
    # file against the state directory.
    redactor = Redactor.from_config(cfg, state_dir=ctx.state_dir)
    findings: list[ValidationFinding] = []
    findings += scan_crate_secrets(crate_dir, redactor)
    findings += journal_findings(
        crate_dir,
        include_event_journal=cfg.privacy.include_event_journal,
        include_prompts=cfg.privacy.include_prompts,
    )
    findings += source_diff_findings(
        crate_dir,
        source_roots=cfg.source_roots,
        include_source_code_public=cfg.privacy.include_source_code_public,
        include_git_diff_public=cfg.privacy.include_git_diff_public,
    )
    findings += env_findings(crate_dir, allowlist=cfg.redaction.environment_allowlist)
    findings += log_findings(
        crate_dir,
        include_full_logs=cfg.privacy.include_full_logs,
        max_log_size_mb=cfg.file_policy.max_log_size_mb,
    )
    metadata = ctx.metadata
    if metadata is not None and not cfg.privacy.include_prompts:
        # Reuse the config redactor so the in-memory metadata scan matches the
        # user's custom secret patterns exactly as the on-disk file scan does.
        for pf in check_public_export_payload(metadata, include_prompts=False, redactor=redactor):
            findings.append(_finding(pf.code, f"Privacy violation at {pf.path}", pf.path))
    return findings


def check_privacy(ctx: ValidationContext) -> list[ValidationFinding]:
    if not ctx.public:
        return []
    if not ctx.cfg.validation.require_privacy_gate:
        return []
    return public_export_findings(ctx)
