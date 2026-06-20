"""Cross-domain helpers shared by the mapping builders.

Small utilities and shared vocabulary that several entity-builder submodules depend on:
reference/PropertyValue node constructors, the crate-internal fragment-id scheme, the
sha256 identifier shape, null-stripping, on-disk content sizing, the schema.org command
action-type classifier, and the Bioschemas FormalParameter profile contextual entity.

The verb/op/status classification tables (`FILE_OP_TYPE`, `DELETE_TOOLS`, `STEP_STATUS_URI`)
live here so every observed-thing → schema.org-class/status-URI mapping is discoverable and
editable in one place.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ro_crate_run import constants
from ro_crate_run.models import CommandRecord, strip_none


def ref(eid: str) -> dict[str, str]:
    """Return a ``{"@id": eid}`` reference node."""
    return {"@id": eid}


def root_ref() -> dict[str, str]:
    """Return a reference to the RO-Crate root dataset entity."""
    return ref(constants.ROOT_DATASET_ID)


def property_value(
    name: str, value: str, *, property_id: str | None = None
) -> dict[str, Any]:
    """Return a schema.org ``PropertyValue`` node with ``name``/``value`` and optional ``propertyID``.

    ``propertyID`` is omitted (rather than emitted as null) when not supplied, matching the
    shape the git/environment builders open-code.
    """
    node: dict[str, Any] = {"@type": "PropertyValue", "name": name, "value": value}
    if property_id is not None:
        node["propertyID"] = property_id
    return node


def sha256_identifier(raw: str) -> dict[str, Any]:
    """Return the sha256 ``PropertyValue`` identifier node for a digest.

    Strips a leading ``sha256:`` prefix so the value carries the bare hex digest, matching the
    identifier shape open-coded in the file/dependency builders.
    """
    return {
        "@type": "PropertyValue",
        "propertyID": "sha256",
        "value": str(raw).replace("sha256:", ""),
    }


def fragment_id(prefix: str, suffix: object) -> str:
    """Return a crate-internal fragment ``@id`` (``#<prefix>/<suffix>``).

    Centralizes the per-family crate-internal id scheme (``#file-action/<seq>`` etc.) so the
    namespace is constructed in one place rather than ad hoc f-strings. ``suffix`` is typically a
    sequence number or string id; it is rendered with ``str()`` exactly as an f-string would.
    """
    return f"#{prefix}/{suffix}"


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


# How an observed file mutation verb maps to a schema.org action type.
FILE_OP_TYPE = {
    "created": "CreateAction",
    "modified": "UpdateAction",
    "changed": "UpdateAction",
    "deleted": "DeleteAction",
}

# Tool basenames whose invocation is a deletion (drives DeleteAction classification).
DELETE_TOOLS = {"rm", "rmdir", "del", "unlink"}

# How a step lifecycle status maps to a schema.org actionStatus URI.
STEP_STATUS_URI = {
    "started": constants.ACTION_STATUS_ACTIVE,
    "completed": constants.ACTION_STATUS_COMPLETED,
    "failed": constants.ACTION_STATUS_FAILED,
    "skipped": constants.ACTION_STATUS_FAILED,
}


def command_action_type(cmd: CommandRecord) -> str:
    """Return the appropriate schema.org action type for a command."""
    tool = os.path.basename(cmd.argv[0]) if cmd.argv else ""
    if tool in DELETE_TOOLS:
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


def root_creative_work(
    entity_id: str, name: str, text: str, *, description: str | None = None
) -> dict[str, Any]:
    """Return a ``CreativeWork`` annotation attached to the root dataset.

    The shared shape for prompts and public notes/decisions: a textual annotation whose
    ``about`` points at the crate root. ``description`` is omitted when not supplied.
    """
    entity: dict[str, Any] = {
        "@id": entity_id,
        "@type": "CreativeWork",
        "name": name,
        "text": text,
        "about": root_ref(),
    }
    if description is not None:
        entity["description"] = description
    return entity


# ``strip_none`` (recursive, owned by models) is the single canonical null-stripper used by
# the mapping builders; re-exported here so callers import it from one place. Mapping entities
# never carry nested ``None``, so the recursive strip is byte-identical to a shallow one.

__all__ = [
    "DELETE_TOOLS",
    "FILE_OP_TYPE",
    "STEP_STATUS_URI",
    "command_action_type",
    "fragment_id",
    "property_value",
    "ref",
    "root_creative_work",
    "root_ref",
    "sha256_identifier",
    "strip_none",
]
