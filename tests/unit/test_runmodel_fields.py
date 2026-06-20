from __future__ import annotations

from dataclasses import replace

from ro_crate_run.models import RunModel, strip_none


def _base_run_model() -> RunModel:
    return RunModel(
        run_id="run-1",
        title="t",
        description="d",
        created_at="2026-06-20T00:00:00Z",
        updated_at="2026-06-20T00:00:00Z",
        selected_profile="process",
        requested_profile="process",
        profile_uri="https://example.org/profile",
        mode="monitored",
    )


def test_profile_confidence_defaults_to_none() -> None:
    model = _base_run_model()
    assert model.profile_confidence is None


def test_profile_evidence_defaults_to_empty_list() -> None:
    model = _base_run_model()
    assert model.profile_evidence == []


def test_profile_evidence_default_is_independent_per_instance() -> None:
    a = _base_run_model()
    b = _base_run_model()
    a.profile_evidence.append("workflow-evidence")
    assert b.profile_evidence == []


def test_set_profile_fields_round_trip_through_strip_none() -> None:
    model = replace(
        _base_run_model(),
        profile_confidence="high",
        profile_evidence=["step-evidence", "command-evidence"],
    )
    payload = {
        "confidence": model.profile_confidence,
        "evidence": list(model.profile_evidence),
        "dropped": None,
    }
    cleaned = strip_none(payload)
    assert cleaned == {
        "confidence": "high",
        "evidence": ["step-evidence", "command-evidence"],
    }
    # The set fields are unaffected by the None-stripping pass.
    assert model.profile_confidence == "high"
    assert model.profile_evidence == ["step-evidence", "command-evidence"]
