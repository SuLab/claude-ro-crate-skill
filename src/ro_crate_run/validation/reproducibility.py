from __future__ import annotations

from typing import Any

from ro_crate_run.models import ValidationFinding

from .context import ValidationContext

_LOCKFILES = {
    "requirements.txt", "pyproject.toml", "poetry.lock", "uv.lock", "environment.yml",
    "package-lock.json", "pnpm-lock.yaml", "renv.lock", "Snakefile", "nextflow.config",
}


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

    # 1. Missing git commit
    if not git.get("commit"):
        warn("missing_git_commit", "No Git commit recorded", required=vcfg.require_git_commit)
    # 2. Dirty tree without diff
    if git.get("dirty") and not git.get("diff_path"):
        warn("dirty_tree_no_diff", "Working tree was dirty and no diff captured", required=vcfg.require_clean_git)
    # 3. Missing software versions
    if not ctx.state.known_software:
        warn(
            "missing_software_versions",
            "No software versions declared",
            required=vcfg.require_software_versions and ctx.strict,
        )
    # 4. Missing hashes for local inputs
    for declared in ctx.state.declared_inputs:
        path = str(declared.get("path", ""))
        if declared.get("existence", "").startswith("observed") and not declared.get("sha256"):
            findings.append(ValidationFinding("reproducibility", "missing_input_hash", f"Local input not hashed: {path}", path=path))
    # 5. Missing declared outputs
    if not ctx.state.declared_outputs:
        warn("no_declared_outputs", "No outputs declared", required=vcfg.require_declared_outputs and ctx.strict)
    # 6. Missing environment summary
    if not env.get("os") and not env.get("python"):
        findings.append(ValidationFinding("reproducibility", "missing_environment_summary", "No environment summary observed"))
    # 7. Missing container digest for containerized run
    containers = [e for e in ctx.events if e.get("event_type") == "container.observed"]
    for c in containers:
        payload = c.get("payload", {})
        if isinstance(payload, dict) and not payload.get("digest"):
            findings.append(ValidationFinding("reproducibility", "missing_container_digest", "Container observed without digest"))
    # 8. Missing lockfiles for dependency-managed projects
    has_lockfile_event = any(e.get("event_type") == "dependency.lockfile.observed" for e in ctx.events)
    if not has_lockfile_event and any((project_dir / name).exists() for name in _LOCKFILES):
        findings.append(ValidationFinding("reproducibility", "missing_lockfiles", "Dependency lockfiles present but not recorded"))
    # 9. Missing human rationale for manual parameter changes
    param_events = [e for e in ctx.events if e.get("event_type") == "workflow.parameter.declared"]
    decision_events = [e for e in ctx.events if e.get("event_type") == "human.decision"]
    if param_events and not decision_events:
        findings.append(ValidationFinding("reproducibility", "missing_parameter_rationale", "Parameters declared without any human rationale"))
    # 10. Stale crate (SPEC §18.3)
    if ctx.state.dirty:
        warn(
            "crate_stale",
            "Provenance events exist after the last checkpoint (stale crate)",
            required=ctx.strict,
        )
    return findings
