from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ro_crate_run.journal import EventWriter
from ro_crate_run.models import ValidationFinding, ValidationReport

from .context import build_context
from .journal import check_journal
from .privacy import check_privacy
from .profiles import check_profile
from .reproducibility import check_reproducibility
from .rocrate import check_rocrate
from .shacl import check_shacl
from .state import check_state

_LEVELS = ("journal", "state", "ro_crate", "profile", "reproducibility", "privacy")

_RECOMMENDATIONS = {
    "missing_software_versions": "Record tool versions with `rcr software <command>`.",
    "missing_software_versions_required": "Record tool versions with `rcr software <command>`.",
    "missing_git_commit": "Commit your work so the crate references a Git commit.",
    "missing_git_commit_required": "Commit your work so the crate references a Git commit.",
    "dirty_tree_no_diff": "Commit changes or enable git-diff capture for a clean provenance record.",
    "missing_input_hash": "Re-declare local inputs so they are hashed.",
    "no_declared_outputs": "Declare run outputs with `rcr output <path>`.",
    "missing_environment_summary": "Run `rcr start` so environment facts are observed.",
    "missing_lockfiles": "Record dependency lockfiles for reproducibility.",
    "secret_pattern": "Run `rcr redact --apply` before public export.",
    "missing_container_digest": "Capture the container digest (e.g. docker inspect --format='{{.Id}}') for reproducibility.",
    "missing_parameter_rationale": "Record parameter decisions with `rcr decision` to explain parameter choices.",
    "file_content_mismatch": "A declared file changed since checkpoint; re-run `rcr checkpoint` to refresh hashes or restore the file.",
}


def validate_run(
    state_dir: Path,
    strict: bool = False,
    public: bool = False,
    append_event: bool = True,
    crate_dir: Path | None = None,
) -> ValidationReport:
    ctx = build_context(state_dir, strict=strict, public=public, crate_dir=crate_dir)

    findings: list[ValidationFinding] = []
    findings += check_journal(ctx)
    findings += check_state(ctx)
    findings += check_rocrate(ctx)
    findings += check_profile(ctx)
    findings += check_reproducibility(ctx)
    findings += check_shacl(ctx)
    findings += check_privacy(ctx)

    errors = [f for f in findings if _is_error(f)]
    warnings = [f for f in findings if f not in errors]

    levels: dict[str, str] = {name: "passed" for name in _LEVELS}
    for finding in warnings:
        if levels.get(finding.level) == "passed":
            levels[finding.level] = "warning"
    for finding in errors:
        levels[finding.level] = "failed"

    status = "failed" if errors else "warning" if warnings else "passed"
    recommendations = sorted({_RECOMMENDATIONS[f.code] for f in findings if f.code in _RECOMMENDATIONS})
    report = ValidationReport(
        status, ctx.state.selected_profile, ctx.state.profile_uri, levels, errors, warnings, recommendations
    )

    report_path = state_dir / "ro-crate" / "validation-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(_report_dict(report), indent=2, sort_keys=True) + "\n")
    if append_event:
        EventWriter(state_dir).append(
            "crate.validation.completed" if status != "failed" else "crate.validation.failed",
            _report_dict(report),
            source_kind="validator",
        )
    return report


_PROFILE_WARNING_CODES = {
    "open_phase",
    "open_step",
    # L3 Workflow checks: structural quality findings, not hard errors in non-strict mode.
    "workflow_no_action_uses_instrument",
    "workflow_missing_formal_parameters",
    "parameter_value_missing_exampleOfWork",
    # D5: no-action warning (non-strict process crate)
    "no_actions",
}


def _is_error(finding: ValidationFinding) -> bool:
    # Privacy findings are always errors.
    if finding.level == "privacy":
        return True
    # Reproducibility findings are warnings unless they carry the policy-required suffix.
    if finding.level == "reproducibility":
        return finding.code.endswith("_required")
    # Named warning codes are never errors.
    if finding.code in _PROFILE_WARNING_CODES:
        return False
    return True


def _report_dict(report: ValidationReport) -> dict[str, Any]:
    return {
        "status": report.status,
        "profile": report.profile,
        "profile_uri": report.profile_uri,
        "levels": report.levels,
        "errors": [f.__dict__ for f in report.errors],
        "warnings": [f.__dict__ for f in report.warnings],
        "recommendations": report.recommendations,
    }
