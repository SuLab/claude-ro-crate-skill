"""File / Dataset entity builder.

``build_file_entity`` turns one ``FilePlan`` into a File (or Dataset) entity,
honoring the sensitive-file policy (content-free reference only) and recording
hash / size / existence-classification provenance.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ._helpers import property_value, sha256_identifier, strip_none


def build_file_entity(
    plan: Any, max_hash_bytes: int, formal_parameter_id: str | None = None
) -> dict[str, Any]:
    """Return a File or Dataset entity for one ``FilePlan``."""
    from ro_crate_run.fs import file_record

    declared = getattr(plan, "declared", {}) or {}
    if getattr(plan, "sensitive", False):
        # Never read content (no hash, no size) — only a content-free reference.
        sensitive_entity: dict[str, Any] = {
            "@id": plan.file_id,
            "@type": "File",
            "name": os.path.basename(plan.file_id),
            "description": declared.get("description") or "Sensitive file (never captured)",
            "additionalProperty": property_value(
                None,
                "not-captured",
                property_id="capture-status",
                description="sensitive file; never read, hashed, or copied",
            ),
        }
        if formal_parameter_id:
            sensitive_entity["exampleOfWork"] = {"@id": formal_parameter_id}
        return sensitive_entity
    abs_path: Path = plan.abs_path
    rec = file_record(abs_path, abs_path.parent, max_hash_bytes)
    entity: dict[str, Any] = {
        "@id": plan.file_id,
        "@type": "Dataset" if rec.get("kind") == "directory" else "File",
        "name": os.path.basename(plan.file_id),
        "description": declared.get("description") or declared.get("role") or "Run file",
        "encodingFormat": rec.get("encoding_format"),
        "contentSize": str(rec["content_size"]) if rec.get("content_size") is not None else None,
        "dateModified": rec.get("date_modified"),
    }
    add_props: list[dict[str, Any]] = []
    if rec.get("sha256"):
        entity["identifier"] = sha256_identifier(str(rec["sha256"]))
    elif rec.get("hash_status") == "skipped":
        add_props.append(
            property_value(
                None,
                "not-hashed",
                property_id="hash-status",
                description=str(rec.get("hash_skip_reason", "skipped")),
            )
        )
    # Materialize the declared existence classification (observed-local/remote, generated,
    # expected, missing, declared-only) so a crate consumer can tell an observed input from
    # an expected-but-absent output — otherwise this lives only in state.json.
    existence = declared.get("existence")
    if existence:
        add_props.append(property_value(None, str(existence), property_id="existence"))
    if add_props:
        # additionalProperty is a single PropertyValue dict when only one applies, a list when
        # several, so a lone status reads as a plain object rather than a one-element array.
        entity["additionalProperty"] = add_props[0] if len(add_props) == 1 else add_props
    if formal_parameter_id:
        entity["exampleOfWork"] = {"@id": formal_parameter_id}
    stripped: dict[str, Any] = strip_none(entity)
    return stripped
