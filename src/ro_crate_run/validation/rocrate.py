from __future__ import annotations

from typing import Any

from ro_crate_run.constants import PROFILE_URIS, RO_CRATE_SPEC_URI
from ro_crate_run.files import sha256_file
from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .jsonld import expand_metadata

_ROOT_REQUIRED_ALWAYS = ("name", "description", "license")
_ROOT_REQUIRED_CONDITIONAL = ("datePublished",)


def _recorded_sha256(entity: dict[str, Any]) -> str | None:
    """Return the bare sha256 hex recorded on a File entity, if any.

    The hash is carried as an ``identifier`` PropertyValue (propertyID ``sha256``);
    files skipped for hashing (e.g. over the size limit) carry no such value.
    """
    identifier = entity.get("identifier")
    candidates = identifier if isinstance(identifier, list) else [identifier]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("propertyID") == "sha256":
            value = candidate.get("value")
            if isinstance(value, str) and value:
                return value.replace("sha256:", "")
    return None


def _contains_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_contains_null(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_null(v) for v in value)
    return False


def _is_action_type(value: Any) -> bool:
    values = value if isinstance(value, list) else [value]
    return any(str(item).endswith("Action") for item in values)


def _deleted_file_ids(graph: list[dict[str, Any]]) -> set[str]:
    """@ids of files removed by a recorded DeleteAction — legitimately absent on disk."""
    ids: set[str] = set()
    for entity in graph:
        types = entity.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if "DeleteAction" not in types:
            continue
        for key in ("object", "result"):
            refs = entity.get(key, [])
            refs = refs if isinstance(refs, list) else [refs]
            ids.update(str(r["@id"]) for r in refs if isinstance(r, dict) and r.get("@id"))
    return ids


def check_rocrate(ctx: ValidationContext) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    metadata = ctx.metadata
    if metadata is None:
        if not (ctx.state_dir / "ro-crate" / "ro-crate-metadata.json").exists():
            findings.append(ValidationFinding("ro_crate", "metadata_missing", "ro-crate-metadata.json is missing"))
        else:
            findings.append(ValidationFinding("ro_crate", "metadata_invalid_json", "ro-crate-metadata.json is not valid JSON"))
        return findings

    triples, expand_error = expand_metadata(metadata)
    if expand_error is not None:
        findings.append(ValidationFinding("ro_crate", "jsonld_expansion_failed", f"JSON-LD did not expand: {expand_error}"))
    elif triples == 0:
        findings.append(ValidationFinding("ro_crate", "jsonld_empty", "JSON-LD expanded to zero triples"))

    entities = {e.get("@id"): e for e in metadata.get("@graph", [])}
    descriptor = entities.get("ro-crate-metadata.json")
    root = entities.get("./")

    if not descriptor or descriptor.get("conformsTo", {}).get("@id") != RO_CRATE_SPEC_URI:
        findings.append(ValidationFinding("ro_crate", "descriptor_invalid_conforms_to", "Descriptor must conform to RO-Crate 1.2"))
    if not descriptor or descriptor.get("about", {}).get("@id") != "./":
        findings.append(ValidationFinding("ro_crate", "descriptor_about_invalid", "Descriptor must point to root"))

    if not root:
        findings.append(ValidationFinding("ro_crate", "root_missing", "Root Data Entity is missing"))
        return findings

    if root.get("@type") != "Dataset" and "Dataset" not in root.get("@type", []):
        findings.append(ValidationFinding("ro_crate", "root_not_dataset", "Root must be Dataset"))
    for key in _ROOT_REQUIRED_ALWAYS:
        if key not in root:
            findings.append(ValidationFinding("ro_crate", f"root_missing_{key}", f"Root missing {key}"))
    if ctx.cfg.validation.require_date_published and "datePublished" not in root:
        findings.append(ValidationFinding("ro_crate", "root_missing_datePublished", "Root missing datePublished"))

    conforms = root.get("conformsTo", [])
    if isinstance(conforms, dict):
        conforms = [conforms]
    selected_uri = PROFILE_URIS.get(ctx.state.selected_profile, "")
    if {"@id": ctx.state.profile_uri} not in conforms and {"@id": selected_uri} not in conforms:
        findings.append(ValidationFinding("profile", "root_missing_profile", "Root missing selected profile conformance"))

    if _contains_null(metadata):
        findings.append(ValidationFinding("ro_crate", "json_null_present", "Metadata contains JSON null"))

    if ctx.strict and not [e for e in entities.values() if _is_action_type(e.get("@type"))]:
        findings.append(ValidationFinding("profile", "no_actions", "Strict Process Run Crate requires an action"))

    crate_dir = ctx.state_dir / "ro-crate"
    project_root = ctx.state_dir.parent
    # Files legitimately absent on disk: removed by a recorded DeleteAction, or declared
    # with an existence that does not imply local presence (remote/expected/missing/
    # declared-only). Such entities must not be reported as referenced_file_missing.
    _ABSENT_EXISTENCE = {"observed remote", "expected", "missing", "declared-only"}
    absent_ids = {
        str(d.get("path"))
        for d in (ctx.state.declared_inputs + ctx.state.declared_outputs)
        if d.get("existence") in _ABSENT_EXISTENCE
    }
    exempt_ids = _deleted_file_ids(metadata.get("@graph", [])) | absent_ids
    for entity in metadata.get("@graph", []):
        eid = str(entity.get("@id", ""))
        types = entity.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if "File" not in types and "Dataset" not in types:
            continue
        if eid.startswith(("http://", "https://", "urn:", "file:", "#", "./")) or eid == "ro-crate-metadata.json":
            continue
        if entity.get("contentUrl") or entity.get("external"):
            continue
        crate_path = crate_dir / eid
        project_path = project_root / eid
        resolved = crate_path if crate_path.exists() else project_path if project_path.exists() else None
        if resolved is None:
            if eid not in exempt_ids:
                findings.append(ValidationFinding("ro_crate", "referenced_file_missing", f"Referenced file not present: {eid}", path=eid))
            continue
        # Content integrity: a crate's recorded sha256 must match the bytes on disk.
        # Re-hashing catches post-checkpoint drift of declared inputs/outputs and corruption
        # of embedded copies — without it, a stale/false hash passes validation silently.
        # Both the embedded crate copy AND the live project file are checked: when an output
        # is copied into the crate the embedded copy is immutable, so a tampered project-side
        # file would otherwise be masked. Files exempt from presence checks (DeleteAction
        # targets, remote/expected/missing/declared-only) are also exempt from content checks.
        if "File" in types and eid not in exempt_ids:
            recorded = _recorded_sha256(entity)
            if recorded is not None:
                disk_paths = [crate_path, project_path] if crate_path != project_path else [crate_path]
                for disk_path in disk_paths:
                    if disk_path.is_file() and sha256_file(disk_path).replace("sha256:", "") != recorded:
                        findings.append(
                            ValidationFinding(
                                "ro_crate",
                                "file_content_mismatch",
                                f"Recorded sha256 does not match file content: {eid}",
                                path=eid,
                            )
                        )
                        break
    return findings
