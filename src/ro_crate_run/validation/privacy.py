from __future__ import annotations

import json
from pathlib import Path

from ..models import ValidationFinding
from ..privacy import check_public_export_payload
from ..redaction import Redactor
from .context import ValidationContext


def scan_crate_secrets(crate_dir: Path, redactor: Redactor) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for path in sorted(crate_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if redactor.redact_text(text).applied:
            rel = path.relative_to(crate_dir).as_posix()
            findings.append(
                ValidationFinding("privacy", "secret_pattern", f"Secret pattern found in {rel}", rel)
            )
    return findings


def journal_findings(
    crate_dir: Path, *, include_event_journal: bool, include_prompts: bool
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for journal in sorted(crate_dir.rglob("events.ndjson")):
        rel = journal.relative_to(crate_dir).as_posix()
        if not include_event_journal:
            findings.append(
                ValidationFinding(
                    "privacy",
                    "event_journal_in_public_export",
                    f"Event journal present in public crate without include_event_journal: {rel}",
                    rel,
                )
            )
        if not include_prompts and _journal_has_prompt(journal):
            findings.append(
                ValidationFinding(
                    "privacy",
                    "raw_prompt_in_public_export",
                    f"Raw prompt present in public crate without include_prompts: {rel}",
                    rel,
                )
            )
    return findings


def _journal_has_prompt(journal: Path) -> bool:
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event_type") == "human.prompt":
            return True
    return False


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
                    ValidationFinding(
                        "privacy",
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
                ValidationFinding(
                    "privacy",
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
                    ValidationFinding(
                        "privacy",
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
    limit = max_log_size_mb * 1024 * 1024
    findings: list[ValidationFinding] = []
    for log in sorted(crate_dir.rglob("logs/*.txt")):
        if log.is_file() and log.stat().st_size > limit:
            rel = log.relative_to(crate_dir).as_posix()
            findings.append(
                ValidationFinding(
                    "privacy",
                    "full_log_in_public_export",
                    f"Oversized log in public crate without include_full_logs: {rel}",
                    rel,
                )
            )
    return findings


def public_export_findings(ctx: ValidationContext) -> list[ValidationFinding]:
    crate_dir: Path = ctx.crate_dir if ctx.crate_dir is not None else ctx.state_dir / "ro-crate"
    cfg = ctx.cfg
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
        for pf in check_public_export_payload(metadata, include_prompts=False):
            findings.append(
                ValidationFinding("privacy", pf.code, f"Privacy violation at {pf.path}", pf.path)
            )
    return findings


def check_privacy(ctx: ValidationContext) -> list[ValidationFinding]:
    if not ctx.public:
        return []
    if not ctx.cfg.validation.require_privacy_gate:
        return []
    return public_export_findings(ctx)
