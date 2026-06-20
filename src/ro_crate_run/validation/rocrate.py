"""Validation level 2 (RO-Crate structure): real JSON-LD expansion plus the
base RO-Crate 1.2 MUSTs — descriptor/root shape, no anonymous nodes, hasPart
reachability, referenced-file presence, and recorded-hash integrity."""

from __future__ import annotations

from typing import Any

from ro_crate_run.constants import PROFILE_URIS, RO_CRATE_SPEC_URI, is_web_id
from ro_crate_run.fs import sha256_file
from ro_crate_run.models import ValidationFinding

from .context import ValidationContext
from .graphview import types_of
from .jsonld import expand_metadata

_ROOT_REQUIRED_ALWAYS = ("name", "description", "license")
_ROOT_REQUIRED_CONDITIONAL = ("datePublished",)


def _deref(candidate: Any, entities: dict[Any, dict[str, Any]]) -> Any:
    """Resolve a PropertyValue that is a ``{"@id": ...}`` reference to its promoted
    top-level node. The materializer node-ifies nested typed dicts (RO-Crate 1.2 MUST:
    no anonymous inlining), so an ``identifier``/``additionalProperty`` value is a bare
    reference rather than an inline dict; resolve it before reading propertyID/value.
    Inline dicts (legacy) pass through unchanged."""
    if isinstance(candidate, dict) and set(candidate.keys()) == {"@id"}:
        return entities.get(candidate["@id"], candidate)
    return candidate


def _recorded_sha256(entity: dict[str, Any], entities: dict[Any, dict[str, Any]]) -> str | None:
    """Return the bare sha256 hex recorded on a File entity, if any.

    The hash is carried as an ``identifier`` PropertyValue (propertyID ``sha256``);
    files skipped for hashing (e.g. over the size limit) carry no such value.
    """
    identifier = entity.get("identifier")
    candidates = identifier if isinstance(identifier, list) else [identifier]
    for candidate in candidates:
        candidate = _deref(candidate, entities)
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


def _deleted_file_ids(graph: list[dict[str, Any]]) -> set[str]:
    """@ids of files removed by a recorded DeleteAction — legitimately absent on disk."""
    ids: set[str] = set()
    for entity in graph:
        if "DeleteAction" not in types_of(entity):
            continue
        for key in ("object", "result"):
            refs = entity.get(key, [])
            refs = refs if isinstance(refs, list) else [refs]
            ids.update(str(r["@id"]) for r in refs if isinstance(r, dict) and r.get("@id"))
    return ids


def _entity_existence(entity: dict[str, Any], entities: dict[Any, dict[str, Any]]) -> str | None:
    """The existence class materialized on a File/Dataset entity (its `existence`
    additionalProperty PropertyValue), or None."""
    ap = entity.get("additionalProperty")
    for prop in (ap if isinstance(ap, list) else [ap]):
        prop = _deref(prop, entities)
        if isinstance(prop, dict) and prop.get("propertyID") == "existence":
            return str(prop.get("value"))
    return None


def _find_anonymous_nodes(value: Any) -> list[dict[str, Any]]:
    """Recursively collect dicts that carry an ``@type`` but neither an ``@id``
    nor an ``@value`` — anonymous (un-identified) entities.

    RO-Crate 1.2 base MUST (01-rocrate12-base.md lines 49-50): nested entities MUST
    be separate contextual entities in the flat @graph (no anonymous inlining) and
    every entity MUST have an ``@id``. A dict with ``@type`` but no ``@id``/``@value``
    is an entity reference that was inlined without an identifier — a MUST violation.
    A dict carrying ``@value`` is a typed JSON-LD literal (not an entity), so it is
    exempt. Dicts that are pure references (``{"@id": ...}`` with no ``@type``) are
    also fine.
    """
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "@type" in value and "@id" not in value and "@value" not in value:
            found.append(value)
        for v in value.values():
            found.extend(_find_anonymous_nodes(v))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_anonymous_nodes(item))
    return found


def _haspart_reachable(graph: list[dict[str, Any]]) -> set[str]:
    """The set of @ids reachable from the Root Data Entity ``./`` by following
    ``hasPart`` edges only (a hasPart-only walk).

    RO-Crate 1.2 base MUST (01-rocrate12-base.md line 33): data entities MUST be
    linked, directly or indirectly, from the Root Data Entity using the ``hasPart``
    property. Reachability via ``mentions``/``object``/``result`` etc. does NOT
    satisfy this MUST.
    """
    by_id = {str(e.get("@id")): e for e in graph if isinstance(e, dict) and e.get("@id")}
    reachable: set[str] = set()
    frontier = ["./"]
    while frontier:
        current = frontier.pop()
        entity = by_id.get(current)
        if entity is None:
            continue
        parts = entity.get("hasPart", [])
        if isinstance(parts, dict):
            parts = [parts]
        elif not isinstance(parts, list):
            parts = []
        for ref in parts:
            ref_id = ref.get("@id") if isinstance(ref, dict) else ref
            if not isinstance(ref_id, str) or ref_id in reachable:
                continue
            reachable.add(ref_id)
            frontier.append(ref_id)
    return reachable


def _is_local_data_entity(entity: dict[str, Any]) -> bool:
    """True for a File/Dataset data entity whose @id is a relative, non-``#`` path
    (i.e. a packaged local data entity that MUST be reachable via hasPart).

    Web-based (absolute URI) data entities, contextual ``#``-prefixed entities, the
    metadata descriptor, and the root itself are excluded — the hasPart MUST applies
    to packaged relative-path data entities.
    """
    types = types_of(entity)
    if "File" not in types and "Dataset" not in types:
        return False
    eid = str(entity.get("@id", ""))
    if eid in ("", "./", "ro-crate-metadata.json"):
        return False
    if is_web_id(eid) or eid.startswith("#"):
        return False
    return True


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

    entities = ctx.entities
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
        types = types_of(entity)
        if "File" not in types and "Dataset" not in types:
            continue
        if is_web_id(eid) or eid.startswith(("#", "./")) or eid == "ro-crate-metadata.json":
            continue
        if entity.get("contentUrl") or entity.get("external"):
            continue
        crate_path = crate_dir / eid
        project_path = project_root / eid
        resolved = crate_path if crate_path.exists() else project_path if project_path.exists() else None
        if resolved is None:
            # Also trust the existence materialized on the entity itself (e.g. imported files
            # carry a declared-only existence but are not in state.declared_*), not only state.
            if eid not in exempt_ids and _entity_existence(entity, entities) not in _ABSENT_EXISTENCE:
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
            recorded = _recorded_sha256(entity, entities)
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

    graph = metadata.get("@graph", [])

    # L2 anonymous-entity check — base MUST: every entity has an @id; nested typed
    # nodes must be promoted to flat @graph entities, never inlined anonymously.
    # We scan the whole document (including values nested inside property objects),
    # so an anonymous PropertyValue buried inside an action's additionalProperty is
    # still caught. Skip the metadata @context blob if present.
    for entity in graph:
        if not isinstance(entity, dict):
            continue
        for node in _find_anonymous_nodes(entity):
            type_hint = node.get("@type")
            findings.append(
                ValidationFinding(
                    "ro_crate",
                    "anonymous_entity",
                    f"Anonymous node with @type={type_hint!r} has no @id (must be a flat, identified entity)",
                )
            )

    # L2 hasPart-reachability check — base MUST: data entities MUST be linked from the
    # root via hasPart (directly or indirectly). A relative-path File/Dataset reachable
    # only via mentions/object/result violates the MUST.
    reachable = _haspart_reachable(graph)
    for entity in graph:
        if not isinstance(entity, dict) or not _is_local_data_entity(entity):
            continue
        eid = str(entity.get("@id"))
        if eid not in reachable:
            findings.append(
                ValidationFinding(
                    "ro_crate",
                    "data_entity_unreachable",
                    f"Data entity not reachable from root via hasPart: {eid}",
                    path=eid,
                )
            )
    return findings
