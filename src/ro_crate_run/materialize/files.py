from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ro_crate_run.models import FilePolicy, RcrConfig, RunModel


@dataclass
class FilePlan:
    file_id: str
    abs_path: Path
    declared: dict[str, Any] = field(default_factory=dict)
    copy: bool = False
    included: bool = False
    reason: str = ""
    sensitive: bool = False


# Files that must NEVER be captured (read, hashed, or copied) regardless of config
# (SPEC §13.1 / privacy policy). Matched case-insensitively against the basename.
_SENSITIVE_GLOBS = [
    ".env", ".env.*", "*.env", "*.pem", "*.key", "id_rsa", "id_ed25519",
    "*.p12", "*.pfx", "*credentials*", "*secret*", "*token*",
]


def _is_sensitive(file_id: str) -> bool:
    base = Path(file_id).name.lower()
    return any(fnmatch.fnmatch(base, glob) for glob in _SENSITIVE_GLOBS)


def _is_ignored(file_id: str, ignore_patterns: list[str]) -> bool:
    candidate = file_id.replace("\\", "/")
    for pattern in ignore_patterns:
        normalized = pattern.replace("**", "*")
        if fnmatch.fnmatch(candidate, normalized):
            return True
    return False


def _safe_resolve(path: Path, project_dir: Path) -> Optional[Path]:
    project = project_dir.resolve()
    try:
        resolved = (path if path.is_absolute() else project / path).resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(project)
    except ValueError:
        return None
    return resolved


def _included_for_role(role: str, fp: FilePolicy) -> bool:
    if role == "input":
        return fp.include_declared_inputs
    if role == "source":
        return fp.include_source_code != "never"
    return fp.include_declared_outputs


def plan_file_inclusion(model: RunModel, cfg: RcrConfig, project_dir: Path) -> list[FilePlan]:
    fp = cfg.file_policy
    max_bytes = fp.max_file_size_mb * 1024 * 1024
    plans: dict[str, FilePlan] = {}

    def consider(path_str: str, role: str, copy_policy: Optional[str], declared: dict[str, Any]) -> None:
        if not path_str:
            return
        raw = Path(path_str)
        resolved = _safe_resolve(raw, project_dir)
        if resolved is None:
            file_id = raw.as_uri() if raw.is_absolute() else str(raw)
            plans.setdefault(
                file_id,
                FilePlan(
                    file_id=file_id,
                    abs_path=raw,
                    declared=declared,
                    copy=False,
                    included=False,
                    reason="outside-project-root",
                ),
            )
            return
        file_id = str(resolved.relative_to(project_dir.resolve()))
        if _is_ignored(file_id, cfg.ignore_patterns):
            return
        if _is_sensitive(file_id):
            # Never read, hash, or copy — only a content-free reference is recorded.
            plans[file_id] = FilePlan(
                file_id=file_id,
                abs_path=resolved,
                declared=declared,
                copy=False,
                included=False,
                reason="sensitive-never-captured",
                sensitive=True,
            )
            return
        included = _included_for_role(role, fp)
        is_file = resolved.exists() and resolved.is_file()
        size_ok = is_file and resolved.stat().st_size <= max_bytes
        if copy_policy == "reference":
            copy, reason = False, "explicit-reference"
        elif not is_file:
            copy, reason = False, "not-a-regular-file"
        elif not size_ok:
            copy, reason = False, "larger-than-max-file-size"
        elif copy_policy == "copy":
            copy, reason = included, ("explicit-copy" if included else "not-included")
        else:
            copy = included and cfg.copy_mode in {"copy", "mixed"}
            reason = "policy-copy" if copy else "referenced"
        plans[file_id] = FilePlan(
            file_id=file_id,
            abs_path=resolved,
            declared=declared,
            copy=copy,
            included=included,
            reason=reason,
        )

    for item in model.inputs:
        consider(str(item.get("path", "")), "input", item.get("copy_policy"), dict(item))
    for item in model.outputs:
        consider(str(item.get("path", "")), "output", item.get("copy_policy"), dict(item))
    for command in model.commands:
        for out in command.outputs:
            consider(out, "output", None, {"path": out, "description": "Command output"})
    for fa in model.file_actions:
        fa_path = str(fa.get("path", ""))
        if fa_path:
            consider(
                fa_path, "output", None,
                {"path": fa_path, "description": f"File {fa.get('op', 'edited')} by the agent"},
            )
    if model.workflow and model.workflow.get("path"):
        consider(str(model.workflow["path"]), "source", None, dict(model.workflow))
    return list(plans.values())


def log_should_copy(rel: str, project_dir: Path, cfg: RcrConfig) -> bool:
    """Return True iff the log/sidecar at `rel` (relative to project_dir) should be copied."""
    fp = cfg.file_policy
    if fp.include_logs == "never":
        return False
    max_log_bytes = fp.max_log_size_mb * 1024 * 1024
    if max_log_bytes == 0:
        return False
    src = project_dir / rel
    if not src.exists() or not src.is_file():
        return False
    if src.stat().st_size > max_log_bytes:
        return False
    return True
