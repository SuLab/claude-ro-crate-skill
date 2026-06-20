from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ro_crate_run.models import RcrConfig, RcrState
from ro_crate_run.validation.context import ValidationContext
from ro_crate_run.validation.profiles import check_profile
from ro_crate_run.validation.rocrate import check_rocrate

# These tests exercise the new conformance validators against SYNTHETIC crate dicts.
# They do NOT depend on the materializer being fixed: the checks must be independently
# correct, so each crate is hand-built to be conformant or to violate one MUST.


def _state(profile: str = "process") -> RcrState:
    return RcrState(
        run_id="run-1",
        title="V",
        created_at="2026-06-20T00:00:00Z",
        updated_at="2026-06-20T00:00:00Z",
        profile_uri="",
        selected_profile=profile,
        requested_profile=profile,
    )


def _ctx(
    tmp_path: Path,
    metadata: dict[str, Any],
    *,
    profile: str = "process",
) -> ValidationContext:
    state = _state(profile)
    return ValidationContext(
        state_dir=tmp_path / ".ro-crate-run",
        state=state,
        cfg=RcrConfig(),
        events=[],
        metadata=metadata,
        active_run=False,
        strict=False,
        public=False,
    )


def _codes(findings: list[Any]) -> set[str]:
    return {f.code for f in findings}


# --------------------------------------------------------------------------- #
# L2: anonymous-entity check (rocrate.py)
# --------------------------------------------------------------------------- #


def _base_graph() -> list[dict[str, Any]]:
    return [
        {
            "@type": "CreativeWork",
            "@id": "ro-crate-metadata.json",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
        },
        {
            "@type": "Dataset",
            "@id": "./",
            "name": "X",
            "description": "x",
            "license": "MIT",
            "datePublished": "2026-06-20",
            "hasPart": [],
        },
    ]


def test_anonymous_inline_property_value_flagged(tmp_path: Path) -> None:
    graph = _base_graph()
    # An action carrying an inline PropertyValue with @type but NO @id — the exact
    # base-spec MUST violation the audit found in emitted crates.
    graph.append(
        {
            "@id": "#action/1",
            "@type": "CreateAction",
            "name": "run",
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "git.dirty", "value": "true"},
            ],
        }
    )
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    anon = [f for f in findings if f.code == "anonymous_entity"]
    assert len(anon) == 1
    assert "PropertyValue" in anon[0].message


def test_conformant_referenced_entities_not_flagged(tmp_path: Path) -> None:
    graph = _base_graph()
    # PropertyValue promoted to a flat, identified entity + referenced by @id.
    graph.append(
        {
            "@id": "#action/1",
            "@type": "CreateAction",
            "name": "run",
            "additionalProperty": [{"@id": "#pv/git-dirty"}],
        }
    )
    graph.append({"@id": "#pv/git-dirty", "@type": "PropertyValue", "name": "git.dirty", "value": "true"})
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    assert "anonymous_entity" not in _codes(findings)


def test_typed_literal_with_value_not_flagged(tmp_path: Path) -> None:
    # A JSON-LD typed literal ({"@type", "@value"}) is NOT an entity and must not fire.
    graph = _base_graph()
    graph.append(
        {
            "@id": "#thing/1",
            "@type": "Thing",
            "dateCreated": {"@type": "xsd:dateTime", "@value": "2026-06-20T00:00:00Z"},
        }
    )
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    assert "anonymous_entity" not in _codes(findings)


def test_plain_id_reference_not_flagged(tmp_path: Path) -> None:
    # A bare reference {"@id": ...} (no @type) is fine.
    graph = _base_graph()
    graph.append({"@id": "#a", "@type": "Thing", "about": {"@id": "./"}})
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    assert "anonymous_entity" not in _codes(findings)


# --------------------------------------------------------------------------- #
# L2: hasPart-reachability check (rocrate.py)
# --------------------------------------------------------------------------- #


def test_data_entity_reachable_via_mentions_only_is_flagged(tmp_path: Path) -> None:
    graph = _base_graph()
    # Root links the file ONLY via mentions, not hasPart -> MUST violation.
    graph[1]["mentions"] = [{"@id": "out.txt"}]
    graph.append({"@id": "out.txt", "@type": "File", "name": "out"})
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    unreachable = [f for f in findings if f.code == "data_entity_unreachable"]
    assert [f.path for f in unreachable] == ["out.txt"]


def test_data_entity_reachable_via_haspart_not_flagged(tmp_path: Path) -> None:
    graph = _base_graph()
    graph[1]["hasPart"] = [{"@id": "out.txt"}]
    graph.append({"@id": "out.txt", "@type": "File", "name": "out"})
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    assert "data_entity_unreachable" not in _codes(findings)


def test_data_entity_reachable_indirectly_via_dataset_haspart(tmp_path: Path) -> None:
    # Indirect reachability: root -> subdir/ -> subdir/out.txt, all via hasPart.
    graph = _base_graph()
    graph[1]["hasPart"] = [{"@id": "subdir/"}]
    graph.append({"@id": "subdir/", "@type": "Dataset", "name": "d", "hasPart": [{"@id": "subdir/out.txt"}]})
    graph.append({"@id": "subdir/out.txt", "@type": "File", "name": "out"})
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    assert "data_entity_unreachable" not in _codes(findings)


def test_contextual_and_absolute_entities_exempt_from_haspart(tmp_path: Path) -> None:
    # #-prefixed contextual entity and an absolute-URI (web-based) data entity are
    # NOT subject to the hasPart MUST.
    graph = _base_graph()
    graph.append({"@id": "#ctx/1", "@type": "File", "name": "ctx"})
    graph.append({"@id": "https://example.org/remote.txt", "@type": "File", "name": "remote"})
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    assert "data_entity_unreachable" not in _codes(findings)


# --------------------------------------------------------------------------- #
# L3 provenance: HowToStep.workExample (profiles.py)
# --------------------------------------------------------------------------- #


def _prov_graph() -> list[dict[str, Any]]:
    # Minimal provenance crate skeleton: workflow + one step + a control action so the
    # other provenance checks (missing_steps / missing_control_action) stay quiet and we
    # isolate the new findings.
    return [
        {"@type": "CreativeWork", "@id": "ro-crate-metadata.json", "about": {"@id": "./"}},
        {
            "@type": "Dataset",
            "@id": "./",
            "name": "X",
            "description": "x",
            "license": "MIT",
            "mainEntity": {"@id": "main.smk"},
            "hasPart": [{"@id": "main.smk"}],
        },
        {
            "@id": "main.smk",
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow", "HowTo"],
            "name": "wf",
            "step": [{"@id": "#step/s1"}],
            "hasPart": [{"@id": "#software/tool"}],
            "input": [],
            "output": [],
        },
        {"@id": "#step/s1", "@type": "HowToStep", "workExample": {"@id": "#software/tool"}},
        {"@id": "#software/tool", "@type": "SoftwareApplication", "name": "tool"},
        {
            "@id": "#action/run",
            "@type": "CreateAction",
            "instrument": {"@id": "main.smk"},
            "startTime": "2026-06-20T00:00:00Z",
            "endTime": "2026-06-20T00:01:00Z",
            "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
        },
        {"@id": "#control/c1", "@type": "ControlAction", "instrument": {"@id": "#step/s1"}},
    ]


def test_provenance_conformant_crate_no_new_findings(tmp_path: Path) -> None:
    findings = check_profile(_ctx(tmp_path, {"@graph": _prov_graph()}, profile="provenance"))
    codes = _codes(findings)
    assert "step_missing_workexample" not in codes
    assert "workflow_missing_haspart" not in codes


def test_step_missing_workexample_flagged(tmp_path: Path) -> None:
    graph = _prov_graph()
    # Strip workExample off the step -> provenance MUST violation.
    for e in graph:
        if e.get("@id") == "#step/s1":
            del e["workExample"]
    findings = check_profile(_ctx(tmp_path, {"@graph": graph}, profile="provenance"))
    missing = [f for f in findings if f.code == "step_missing_workexample"]
    assert len(missing) == 1
    assert "#step/s1" in missing[0].message


def test_step_check_only_runs_for_provenance(tmp_path: Path) -> None:
    # A HowToStep without workExample in a NON-provenance profile is not checked here.
    graph = _prov_graph()
    for e in graph:
        if e.get("@id") == "#step/s1":
            del e["workExample"]
    findings = check_profile(_ctx(tmp_path, {"@graph": graph}, profile="workflow"))
    assert "step_missing_workexample" not in _codes(findings)


# --------------------------------------------------------------------------- #
# L3 provenance: ComputationalWorkflow.hasPart (profiles.py)
# --------------------------------------------------------------------------- #


def test_workflow_missing_haspart_flagged(tmp_path: Path) -> None:
    graph = _prov_graph()
    for e in graph:
        if e.get("@id") == "main.smk":
            del e["hasPart"]
    findings = check_profile(_ctx(tmp_path, {"@graph": graph}, profile="provenance"))
    missing = [f for f in findings if f.code == "workflow_missing_haspart"]
    assert len(missing) == 1
    assert "main.smk" in missing[0].message


def test_workflow_without_steps_not_flagged_for_haspart(tmp_path: Path) -> None:
    # A workflow with no `step` property does not require hasPart-of-tools here.
    graph = _prov_graph()
    for e in graph:
        if e.get("@id") == "main.smk":
            del e["hasPart"]
            del e["step"]
    findings = check_profile(_ctx(tmp_path, {"@graph": graph}, profile="provenance"))
    assert "workflow_missing_haspart" not in _codes(findings)


def test_new_provenance_findings_are_errors(tmp_path: Path) -> None:
    # The two new provenance findings must be hard errors (MUST violations), per the
    # validator severity model (level="profile", not in the warning-code allowlist).
    from ro_crate_run.validation.validator import _is_error

    graph = _prov_graph()
    for e in graph:
        if e.get("@id") == "#step/s1":
            del e["workExample"]
        if e.get("@id") == "main.smk":
            del e["hasPart"]
    findings = check_profile(_ctx(tmp_path, {"@graph": graph}, profile="provenance"))
    for f in findings:
        if f.code in {"step_missing_workexample", "workflow_missing_haspart"}:
            assert _is_error(f) is True


def test_new_rocrate_findings_are_errors(tmp_path: Path) -> None:
    from ro_crate_run.validation.validator import _is_error

    graph = _base_graph()
    graph[1]["mentions"] = [{"@id": "out.txt"}]
    graph.append({"@id": "out.txt", "@type": "File", "name": "out"})
    graph.append(
        {
            "@id": "#action/1",
            "@type": "CreateAction",
            "additionalProperty": [{"@type": "PropertyValue", "name": "x", "value": "y"}],
        }
    )
    findings = check_rocrate(_ctx(tmp_path, {"@graph": graph}))
    for f in findings:
        if f.code in {"anonymous_entity", "data_entity_unreachable"}:
            assert _is_error(f) is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
