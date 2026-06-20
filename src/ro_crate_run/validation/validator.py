"""Layered validation entry point: composes one checker per level (L0 journal
through L5 privacy, plus optional SHACL) into a single ValidationReport and
persists it."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ro_crate_run.journal import EventWriter
from ro_crate_run.models import ValidationFinding, ValidationReport

from .context import ValidationContext, build_context
from .journal import check_journal
from .privacy import check_privacy
from .profiles import check_profile
from .reproducibility import check_reproducibility
from .rocrate import check_rocrate
from .shacl import check_shacl
from .state import check_state

# Ordered pipeline of (level-name, checker). The name labels the level a checker
# primarily emits under; SHACL is filed with the ro_crate level, so its findings
# collapse into that level rather than introducing a separate one.
CHECKS: tuple[tuple[str, Callable[[ValidationContext], list[ValidationFinding]]], ...] = (
    ("journal", check_journal),
    ("state", check_state),
    ("ro_crate", check_rocrate),
    ("profile", check_profile),
    ("reproducibility", check_reproducibility),
    ("ro_crate", check_shacl),
    ("privacy", check_privacy),
)

# De-duplicated ordered level names reported in the levels summary.
_LEVELS = tuple(dict.fromkeys(name for name, _ in CHECKS))

# Keyed by the base finding code; a trailing _required is stripped before lookup,
# so the policy-required variant of each warning reuses the same recommendation.
_RECOMMENDATIONS = {
    "missing_software_versions": "Record tool versions with `rcr software <command>`.",
    "missing_git_commit": "Commit your work so the crate references a Git commit.",
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
    """Run every validation level in order and return a single ValidationReport.

    Composes the L0-journal through L5-privacy checkers (plus optional SHACL),
    classifies each finding as an error or warning, writes the report to
    ro-crate/validation-report.json, and (unless append_event is False) records
    the validation outcome on the journal.
    """
    ctx = build_context(state_dir, strict=strict, public=public, crate_dir=crate_dir)
    if append_event:
        EventWriter(state_dir).append(
            "crate.validation.started", {"strict": strict, "public": public},
            source_kind="validator",
        )

    findings: list[ValidationFinding] = []
    for _name, check in CHECKS:
        findings += check(ctx)

    errors = [f for f in findings if _is_error(f)]
    warnings = [f for f in findings if f not in errors]

    levels: dict[str, str] = {name: "passed" for name in _LEVELS}
    for finding in warnings:
        if levels.get(finding.level) == "passed":
            levels[finding.level] = "warning"
    for finding in errors:
        levels[finding.level] = "failed"

    status = "failed" if errors else "warning" if warnings else "passed"
    recommendations = sorted(
        {
            _RECOMMENDATIONS[k]
            for f in findings
            if (k := f.code.removesuffix("_required")) in _RECOMMENDATIONS
        }
    )
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
    # Workflow structural-quality findings: downgraded to warnings outside strict mode.
    "workflow_no_action_uses_instrument",
    "workflow_missing_formal_parameters",
    "parameter_value_missing_exampleOfWork",
    # A process crate with no recorded actions is a warning, not an error, in non-strict mode.
    "no_actions",
}


def _is_error(finding: ValidationFinding) -> bool:
    """Single authority for finding severity: True classifies the finding as an
    error, False as a warning."""
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
