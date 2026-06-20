"""Validation level 4 (reproducibility): non-blocking warnings about gaps that
weaken a re-run — missing git commit, software versions, hashes, lockfiles,
container digests, and lineage. A finding is an error only when its code ends
in ``_required``."""

from __future__ import annotations

from typing import Any

from ro_crate_run.constants import DEPENDENCY_MANIFESTS
from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .graphview import is_action


def _env_observed(ctx: ValidationContext) -> dict[str, Any]:
    for event in reversed(ctx.events):
        if event.get("event_type") == "environment.observed":
            payload = event.get("payload", {})
            return payload if isinstance(payload, dict) else {}
    return {}


def check_reproducibility(ctx: ValidationContext) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    env = _env_observed(ctx)
    git = env.get("git", {}) if isinstance(env.get("git"), dict) else {}
    project_dir = ctx.state_dir.parent
    vcfg = ctx.cfg.validation

    def warn(code: str, message: str, *, required: bool) -> None:
        if required:
            findings.append(ValidationFinding("reproducibility", f"{code}_required", f"{message} (required by policy)"))
        else:
            findings.append(ValidationFinding("reproducibility", code, message))

    # Missing git commit
    if not git.get("commit"):
        warn("missing_git_commit", "No Git commit recorded", required=vcfg.require_git_commit)
    # Dirty working tree but no captured diff file recorded on the git model
    if git.get("dirty") and not git.get("diff_file"):
        warn("dirty_tree_no_diff", "Working tree was dirty and no diff captured", required=vcfg.require_clean_git)
    # Missing software versions
    if not ctx.state.known_software:
        warn(
            "missing_software_versions",
            "No software versions declared",
            required=vcfg.require_software_versions and ctx.strict,
        )
    # Missing hashes for local inputs
    for declared in ctx.state.declared_inputs:
        path = str(declared.get("path", ""))
        if declared.get("existence", "").startswith("observed") and not declared.get("sha256"):
            findings.append(ValidationFinding("reproducibility", "missing_input_hash", f"Local input not hashed: {path}", path=path))
    # Missing declared outputs
    if not ctx.state.declared_outputs:
        warn("no_declared_outputs", "No outputs declared", required=vcfg.require_declared_outputs and ctx.strict)
    # Missing environment summary
    if not env.get("os") and not env.get("python"):
        findings.append(ValidationFinding("reproducibility", "missing_environment_summary", "No environment summary observed"))
    # Missing container digest for containerized run
    containers = [e for e in ctx.events if e.get("event_type") == "container.observed"]
    for c in containers:
        payload = c.get("payload", {})
        if isinstance(payload, dict) and not payload.get("digest"):
            findings.append(ValidationFinding("reproducibility", "missing_container_digest", "Container observed without digest"))
    # Missing lockfiles for dependency-managed projects
    has_lockfile_event = any(e.get("event_type") == "dependency.lockfile.observed" for e in ctx.events)
    if not has_lockfile_event and any((project_dir / name).exists() for name in DEPENDENCY_MANIFESTS):
        findings.append(ValidationFinding("reproducibility", "missing_lockfiles", "Dependency lockfiles present but not recorded"))
    # Missing human rationale for manual parameter changes
    param_events = [e for e in ctx.events if e.get("event_type") == "workflow.parameter.declared"]
    decision_events = [e for e in ctx.events if e.get("event_type") == "human.decision"]
    if param_events and not decision_events:
        findings.append(ValidationFinding("reproducibility", "missing_parameter_rationale", "Parameters declared without any human rationale"))
    # Declared output with no producing Action (lineage gap). An output the agent
    # wrote (file.* -> CreateAction) or produced via `rcr run --outputs` links here;
    # a separately-declared output with no producer is flagged so the gap is visible.
    if ctx.metadata:
        produced: set[str] = set()
        for entity in ctx.metadata.get("@graph", []):
            if not is_action(entity):
                continue
            result = entity.get("result") or []
            result = result if isinstance(result, list) else [result]
            for ref in result:
                if isinstance(ref, dict) and ref.get("@id"):
                    produced.add(str(ref["@id"]))
        for declared in ctx.state.declared_outputs:
            path = str(declared.get("path", ""))
            if (
                path
                and path not in produced
                and str(declared.get("existence", "")) in {"generated", "observed local"}
            ):
                findings.append(ValidationFinding(
                    "reproducibility", "output_without_producer",
                    f"Declared output has no producing action (lineage gap): {path}", path=path,
                ))
    # Stale crate: provenance events exist after the last checkpoint.
    if ctx.state.dirty:
        warn(
            "crate_stale",
            "Provenance events exist after the last checkpoint (stale crate)",
            required=ctx.strict,
        )
    return findings
