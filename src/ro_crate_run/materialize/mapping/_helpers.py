"""Cross-domain helpers shared by the mapping builders.

Small utilities and shared vocabulary that several entity-builder submodules depend on:
reference / PropertyValue / SoftwareApplication node constructors, the crate-internal
fragment-id scheme, the sha256 identifier shape, null-stripping, on-disk content sizing, the
schema.org command action-type classifier, and the Bioschemas FormalParameter profile
contextual entity.

The verb/op/status classification tables (`FILE_OP_TYPE`, `DELETE_TOOLS`, `STEP_STATUS_URI`)
live here so every observed-thing → schema.org-class/status-URI mapping is discoverable and
editable in one place.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ro_crate_run import constants
from ro_crate_run.ids import software_entity_id
from ro_crate_run.models import CommandRecord, strip_none


def ref(eid: str) -> dict[str, str]:
    """Return a ``{"@id": eid}`` reference node."""
    return {"@id": eid}


def root_ref() -> dict[str, str]:
    """Return a reference to the RO-Crate root dataset entity."""
    return ref(constants.ROOT_DATASET_ID)


def property_value(
    name: str | None,
    value: str,
    *,
    property_id: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Return a schema.org ``PropertyValue`` node carrying ``value`` and optional metadata.

    Models both flavours of PropertyValue used across the crate: a named property
    (``name`` then ``value``, with ``propertyID`` last) and a status-style property keyed only
    by ``propertyID`` ahead of ``value`` (pass ``name=None``). Each optional field is omitted
    rather than emitted as null. The two flavours order their keys differently, matching the
    hand-written shapes each replaces byte-for-byte: a named node reads ``@type``, ``name``,
    ``value``, ``propertyID``; a name-less node reads ``@type``, ``propertyID``, ``value``.
    ``description`` is appended last in either case.
    """
    node: dict[str, Any] = {"@type": "PropertyValue"}
    if name is not None:
        node["name"] = name
        node["value"] = value
        if property_id is not None:
            node["propertyID"] = property_id
    else:
        if property_id is not None:
            node["propertyID"] = property_id
        node["value"] = value
    if description is not None:
        node["description"] = description
    return node


def sha256_identifier(raw: str) -> dict[str, Any]:
    """Return the sha256 ``PropertyValue`` identifier node for a digest.

    Strips a leading ``sha256:`` prefix so the value carries the bare hex digest.
    """
    return {
        "@type": "PropertyValue",
        "propertyID": "sha256",
        "value": str(raw).replace("sha256:", ""),
    }


def software_application(name: str) -> dict[str, Any]:
    """Return a ``SoftwareApplication`` node identified by the tool/command ``name``.

    The minimal shape (``@id``/``@type``/``name``) for a tool an action references as its
    instrument; the ``@id`` is derived from ``name`` via the shared id scheme.
    """
    return {"@id": software_entity_id(name), "@type": "SoftwareApplication", "name": name}


def ensure_software(name: str, seen: set[str], entities: list[dict[str, Any]]) -> str:
    """Return the ``SoftwareApplication`` @id for ``name``, emitting the node once.

    Dedupes by @id: appends the node to ``entities`` and records it in ``seen`` only the first
    time a given tool is encountered, so repeated references reuse the existing entity.
    """
    sid = software_entity_id(name)
    if sid not in seen:
        seen.add(sid)
        entities.append(software_application(name))
    return sid


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


# ``strip_none`` (recursive, owned by models) is the canonical null-stripper for the mapping
# builders, exposed here so they import it alongside the entity constructors from one place.

__all__ = [
    "DELETE_TOOLS",
    "FILE_OP_TYPE",
    "STEP_STATUS_URI",
    "command_action_type",
    "ensure_software",
    "fragment_id",
    "property_value",
    "ref",
    "root_creative_work",
    "root_ref",
    "sha256_identifier",
    "software_application",
    "strip_none",
]
