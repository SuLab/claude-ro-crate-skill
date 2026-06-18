from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ro_crate_run.redaction import Redactor
from ro_crate_run.validation.validator import validate_run

GOLDEN_ROOT = Path(__file__).resolve().parent


def _types(entity: dict[str, Any]) -> list[str]:
    raw = entity.get("@type")
    return [str(t) for t in (raw if isinstance(raw, list) else [raw]) if t is not None]


def _idref(value: Any) -> Any:
    return value.get("@id") if isinstance(value, dict) else value


def _idrefs(value: Any) -> list[Any]:
    items = value if isinstance(value, list) else [value]
    return sorted(_idref(item) for item in items if item)


def extract_dimensions(crate_dir: Path) -> dict[str, Any]:
    """Reduce a crate to the SPEC §21.3 comparison dimensions, keyed by stable
    values only (entity name, relative @id, #software ids) so urn:uuid /
    timestamp / absolute-path volatility never affects the result."""
    meta = json.loads((crate_dir / "ro-crate-metadata.json").read_text())
    graph = meta.get("@graph", [])
    by_id = {e.get("@id"): e for e in graph}
    root = by_id.get("./", {})

    type_hist: dict[str, int] = {}
    for entity in graph:
        for t in _types(entity):
            type_hist[t] = type_hist.get(t, 0) + 1

    # Build a uuid→stable-name map for action cross-references
    _uuid_to_stable: dict[str, str] = {}
    for entity in graph:
        types = _types(entity)
        eid = str(entity.get("@id", ""))
        if any(t.endswith("Action") for t in types) and eid.startswith("urn:uuid:"):
            name_val = entity.get("name")
            if name_val:
                _uuid_to_stable[eid] = str(name_val)
            elif "ControlAction" in types and entity.get("instrument"):
                _uuid_to_stable[eid] = f"ControlAction/{_idref(entity['instrument'])}"

    def _stable_idrefs(value: Any) -> list[Any]:
        items = value if isinstance(value, list) else ([value] if value else [])
        result = []
        for item in items:
            ref = _idref(item)
            if ref is None:
                continue
            result.append(_uuid_to_stable.get(str(ref), ref))
        return sorted(result)

    actions: dict[str, Any] = {}
    for entity in graph:
        types = _types(entity)
        if any(t.endswith("Action") for t in types):
            # Stable key: use name if present, else derive from type+instrument for ControlActions
            raw_id = entity.get("@id", "")
            name_val = entity.get("name")
            if name_val:
                action_key = str(name_val)
            elif "ControlAction" in types and entity.get("instrument"):
                action_key = f"ControlAction/{_idref(entity['instrument'])}"
            else:
                action_key = str(raw_id)
            actions[action_key] = {
                "type": sorted(types),
                "status": _idref(entity.get("actionStatus")),
                "instrument": _idref(entity.get("instrument")),
                "object": _stable_idrefs(entity.get("object", [])),
                "result": _stable_idrefs(entity.get("result", [])),
                "has_error": "error" in entity,
            }

    file_ids = sorted(
        str(e.get("@id"))
        for e in graph
        if "File" in _types(e)
        and not str(e.get("@id")).startswith(("urn:", "#", "http"))
    )

    # SPEC §21.3: validate the crate and capture the report status as a dimension.
    state_dir = crate_dir.parent
    try:
        report = validate_run(state_dir, strict=False, public=False, append_event=False)
        validation_status = report.status
    except Exception:
        validation_status = "error"

    return {
        "entity_types": dict(sorted(type_hist.items())),
        "root_conformsTo": _idrefs(root.get("conformsTo", [])),
        "root_mainEntity": _idref(root.get("mainEntity")),
        "root_hasPart": _idrefs(root.get("hasPart", [])),
        "root_mentions_count": len(root.get("mentions", []) or []),
        "stable_file_ids": file_ids,
        "actions": dict(sorted(actions.items())),
        "validation_status": validation_status,
    }


def golden_path(name: str) -> Path:
    return GOLDEN_ROOT / name / "expected-dimensions.json"


def load_golden(name: str) -> dict[str, Any] | None:
    path = golden_path(name)
    return json.loads(path.read_text()) if path.exists() else None


def assert_matches_golden(name: str, crate_dir: Path) -> None:
    actual = extract_dimensions(crate_dir)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path = golden_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
        return
    expected = load_golden(name)
    assert expected is not None, (
        f"No golden for {name!r}; run UPDATE_GOLDEN=1 pytest to create it."
    )
    assert actual == expected, (
        f"Crate dimensions diverged from golden {name!r}.\n"
        f"Expected: {json.dumps(expected, indent=2, sort_keys=True)}\n"
        f"Actual:   {json.dumps(actual, indent=2, sort_keys=True)}"
    )


def find_secret_leaks(crate_dir: Path, needles: list[str]) -> list[str]:
    redactor = Redactor.default()
    leaks: list[str] = []
    for path in sorted(crate_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(crate_dir)
        if redactor.redact_text(text).applied:
            leaks.append(f"{rel}: <secret-pattern>")
        for needle in needles:
            if needle in text:
                leaks.append(f"{rel}: {needle}")
    return leaks
