"""Environment, container, dependency, git, and notes/decisions builders.

The provenance-context entity builders: ``build_git`` (repo state + optional diff File),
``build_environment`` (allowlisted env-var PropertyValues), ``build_containers``
(ContainerImage entities), ``build_dependencies`` (lockfile/manifest File entities), and
``build_notes_decisions`` (public CreativeWork notes + decisions).
"""
from __future__ import annotations

import os
from typing import Any

from ro_crate_run.fs import bare_sha256
from ro_crate_run.models import RunModel

from ._helpers import (
    _content_size,
    fragment_id,
    property_value,
    ref,
    root_creative_work,
    sha256_identifier,
    strip_none,
)


def build_git(
    model: RunModel, project_dir: os.PathLike[str] | str | None = None
) -> list[dict[str, Any]]:
    """Emit a #git/state Thing entity (plus optional diff File entity).

    ``project_dir`` (optional) is used only to compute ``contentSize`` on the git-diff
    File entity (base 1.2 SHOULD).
    """
    git = model.git or {}
    if not git.get("available"):
        return []
    props: list[dict[str, Any]] = []
    if git.get("branch"):
        props.append(property_value("branch", str(git["branch"])))
    props.append(property_value("dirty", "true" if git.get("status") else "false"))
    if git.get("remote"):
        props.append(property_value("remote", str(git["remote"])))
    entity: dict[str, Any] = {
        "@id": "#git/state",
        "@type": "Thing",
        "name": "Git repository state",
        "identifier": git.get("commit"),
        "additionalProperty": props,
    }
    entities: list[dict[str, Any]] = [strip_none(entity)]
    if git.get("diff_file"):
        diff_entity: dict[str, Any] = {
            "@id": str(git["diff_file"]),
            "@type": "File",
            "name": "git diff",
            "encodingFormat": "text/x-patch",
            "about": ref("#git/state"),
        }
        if project_dir is not None:
            size = _content_size(str(git["diff_file"]), project_dir)
            if size is not None:
                diff_entity["contentSize"] = size
        entities.append(diff_entity)
    return entities


def build_environment(model: RunModel) -> list[dict[str, Any]]:
    """Emit a PropertyValue entity per allowlisted environment variable."""
    env_vars = (model.environment or {}).get("env_vars", {})
    if not isinstance(env_vars, dict):
        return []
    return [
        {"@id": fragment_id("env", name), **property_value(name, str(value))}
        for name, value in sorted(env_vars.items())
    ]


_DOCKER_IMAGE_TYPE = "https://w3id.org/ro/terms/workflow-run#DockerImage"
_SIF_IMAGE_TYPE = "https://w3id.org/ro/terms/workflow-run#SIFImage"


def _container_additional_type(registry: str, image: str, tag: str) -> str:
    """Derive the ContainerImage additionalType URI from the registry/ref.

    SIF / Singularity / Apptainer references → SIFImage; everything else (OCI/Docker
    registries: docker.io, ghcr.io, quay.io, registry.*, or an unqualified default) → DockerImage.
    The terms are vendored in assets/contexts/workflow-run.jsonld.
    """
    blob = " ".join((registry, image, tag)).lower()
    if image.lower().endswith(".sif") or "singularity" in blob or "apptainer" in blob:
        return _SIF_IMAGE_TYPE
    return _DOCKER_IMAGE_TYPE


def build_containers(model: RunModel) -> list[dict[str, Any]]:
    """Emit a ContainerImage entity per observed container."""
    entities: list[dict[str, Any]] = []
    for idx, container in enumerate(model.containers, start=1):
        digest = bare_sha256(str(container.get("digest", "")))
        entity = {
            "@id": fragment_id("container", idx),
            "@type": "ContainerImage",
            # ContainerImage SHOULD list additionalType (a workflow-run namespace URI)
            # alongside registry + name (Process/Workflow 0.5 SHOULD).
            "additionalType": ref(
                _container_additional_type(
                    str(container.get("registry", "")),
                    str(container.get("image", "")),
                    str(container.get("tag", "")),
                )
            ),
            "registry": container.get("registry"),
            "name": container.get("image"),
            "tag": container.get("tag"),
            "sha256": digest or None,
        }
        entities.append(strip_none(entity))
    return entities


def build_dependencies(
    model: RunModel, project_dir: os.PathLike[str] | str | None = None
) -> list[dict[str, Any]]:
    """Emit a File entity per observed dependency lockfile / manifest.

    Carries the recorded sha256 (captured at scan time) so the manifest is content-verifiable,
    and gives it a sensible description. ``project_dir`` (optional) is used only to populate
    ``contentSize`` (base 1.2 SHOULD).
    """
    entities: list[dict[str, Any]] = []
    for dep in model.dependencies:
        name = os.path.basename(str(dep["path"]))
        kind = str(dep.get("kind", "lockfile")) or "lockfile"
        entity: dict[str, Any] = {
            "@id": str(dep["path"]),
            "@type": "File",
            "name": name,
            "description": f"Dependency manifest ({kind})",
        }
        digest = bare_sha256(str(dep.get("file_record", "")))
        if digest:
            entity["identifier"] = sha256_identifier(digest)
        if project_dir is not None:
            size = _content_size(str(dep["path"]), project_dir)
            if size is not None:
                entity["contentSize"] = size
        entities.append(entity)
    return entities


def build_notes_decisions(model: RunModel) -> list[dict[str, Any]]:
    """Emit CreativeWork entities for public notes and decisions."""
    entities: list[dict[str, Any]] = []
    for idx, note in enumerate(model.notes, start=1):
        if note.get("visibility") == "public":
            entities.append(
                root_creative_work(
                    fragment_id("note", idx), f"Public note {idx}", note.get("text", "")
                )
            )
    for idx, decision in enumerate(model.decisions, start=1):
        if decision.get("visibility") == "public":
            description = (
                f"Rationale: {decision['rationale']}" if decision.get("rationale") else None
            )
            entities.append(
                root_creative_work(
                    fragment_id("decision", idx),
                    f"Decision {idx}",
                    decision.get("text", ""),
                    description=description,
                )
            )
    return entities
