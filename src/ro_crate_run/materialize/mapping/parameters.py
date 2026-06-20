"""FormalParameter / PropertyValue / ParameterConnection builders.

``build_parameters`` emits declared run parameters as FormalParameter + PropertyValue
pairs; ``workflow_formal_parameters`` derives input/output FormalParameters from the
workflow's declared files (workflow-like profiles only); ``build_parameter_connections``
emits ParameterConnection entities for parameters carrying a connection spec.
"""
from __future__ import annotations

import os
from typing import Any

from ro_crate_run import constants
from ro_crate_run.models import RunModel

from ._helpers import (
    _FORMAL_PARAMETER_PROFILE,
    _formal_parameter_profile_entity,
    property_value,
    ref,
)


def build_parameters(model: RunModel) -> list[dict[str, Any]]:
    """Emit FormalParameter + PropertyValue pairs for each declared run parameter."""
    entities: list[dict[str, Any]] = []
    for parameter in model.parameters:
        name = str(parameter.get("name", "parameter"))
        formal_id = str(parameter.get("formal_parameter") or f"#param/{name}")
        value_id = f"#param-value/{name}"
        entities.append(
            {
                "@id": formal_id,
                "@type": "FormalParameter",
                "name": name,
                "additionalType": parameter.get("type", "Text"),
                "valueRequired": True,
                # L2: WfRC 0.5 SHOULD — conformsTo the Bioschemas FormalParameter profile.
                "conformsTo": ref(_FORMAL_PARAMETER_PROFILE),
            }
        )
        entities.append(
            {
                "@id": value_id,
                **property_value(name, str(parameter.get("value", "")), property_id=name),
                "exampleOfWork": ref(formal_id),
            }
        )
    if model.parameters:
        # Emit the referenced Profile contextual entity once so the conformsTo ref resolves.
        entities.append(_formal_parameter_profile_entity())
    return entities


def workflow_formal_parameters(
    model: RunModel,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return (FormalParameter entities, path→formal_parameter_id map) for
    workflow/provenance profiles; returns ([], {}) for process profile."""
    if model.selected_profile not in constants.WORKFLOW_LIKE_PROFILES or not model.workflow:
        return [], {}
    wf_path = str(model.workflow.get("path", ""))
    params: list[dict[str, Any]] = []
    path_map: dict[str, str] = {}
    for kind, items in (("input", model.inputs), ("output", model.outputs)):
        for item in items:
            path = str(item.get("path", ""))
            if not path or path == wf_path or item.get("role") in {"workflow-definition", "config"}:
                # config-role files are plain File entities only, no FormalParameter.
                continue
            fp_id = f"#formal/{kind}/{os.path.basename(path)}"
            path_map[path] = fp_id
            params.append(
                {
                    "@id": fp_id,
                    "@type": "FormalParameter",
                    "name": item.get("role") or os.path.basename(path),
                    "additionalType": "File",
                    "valueRequired": bool(item.get("required", False)),
                    # L2: WfRC 0.5 SHOULD — conformsTo the Bioschemas FormalParameter profile.
                    "conformsTo": ref(_FORMAL_PARAMETER_PROFILE),
                }
            )
    if params:
        params.append(_formal_parameter_profile_entity())
    return params, path_map


def build_parameter_connections(model: RunModel) -> list[dict[str, Any]]:
    """Emit ParameterConnection entities for parameters with a connection spec."""
    entities: list[dict[str, Any]] = []
    for idx, parameter in enumerate(model.parameters, start=1):
        conn = parameter.get("connection")
        if isinstance(conn, dict) and conn.get("source") and conn.get("target"):
            entities.append(
                {
                    "@id": f"#connection/{idx}",
                    "@type": "ParameterConnection",
                    "sourceParameter": ref(str(conn["source"])),
                    "targetParameter": ref(str(conn["target"])),
                }
            )
    return entities
