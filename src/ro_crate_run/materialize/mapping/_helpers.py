"""Cross-domain helpers shared by the mapping builders.

Small utilities that several entity-builder submodules depend on: null-stripping,
on-disk content sizing, the schema.org command action-type classifier, and the
Bioschemas FormalParameter profile contextual entity.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ro_crate_run.models import CommandRecord


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ``d`` with ``None``-valued keys removed."""
    return {k: v for k, v in d.items() if v is not None}


def _content_size(rel: str, project_dir: os.PathLike[str] | str) -> str | None:
    """Return the on-disk byte size (as a str) of a project-relative path, or None.

    Used to populate `contentSize` (base RO-Crate 1.2 SHOULD) on auxiliary File entities
    (command sidecars/logs, git-diff patch, dependency manifests). Absolute paths are
    resolved as-is; relative paths are resolved against the project dir.
    """
    if not rel:
        return None
    p = Path(rel)
    candidate = p if p.is_absolute() else Path(project_dir) / p
    try:
        if candidate.is_file():
            return str(candidate.stat().st_size)
    except OSError:
        return None
    return None


_DELETE_TOOLS = {"rm", "rmdir", "del", "unlink"}


def command_action_type(cmd: CommandRecord) -> str:
    """Return the appropriate schema.org action type for a command."""
    tool = os.path.basename(cmd.argv[0]) if cmd.argv else ""
    if tool in _DELETE_TOOLS:
        return "DeleteAction"
    if cmd.outputs:
        if cmd.inputs and set(cmd.outputs) <= set(cmd.inputs):
            return "UpdateAction"
        return "CreateAction"
    return "Action"


# L2: Bioschemas FormalParameter profile. WfRC 0.5 SHOULD — each FormalParameter
# SHOULD carry conformsTo → this profile permalink.
_FORMAL_PARAMETER_PROFILE = "https://bioschemas.org/profiles/FormalParameter/1.0-RELEASE"


def _formal_parameter_profile_entity() -> dict[str, Any]:
    """The contextual Profile entity the FormalParameter conformsTo refs point at."""
    return {
        "@id": _FORMAL_PARAMETER_PROFILE,
        "@type": ["CreativeWork", "Profile"],
        "name": "Bioschemas FormalParameter profile 1.0-RELEASE",
    }
