from __future__ import annotations

from ro_crate_run import constants


def test_resolve_profile_auto_maps_to_process() -> None:
    selected, uri = constants.resolve_profile("auto")
    assert selected == "process"
    assert uri == constants.PROFILE_URIS["process"]


def test_resolve_profile_process() -> None:
    assert constants.resolve_profile("process") == (
        "process",
        constants.PROFILE_URIS["process"],
    )


def test_resolve_profile_workflow() -> None:
    assert constants.resolve_profile("workflow") == (
        "workflow",
        constants.PROFILE_URIS["workflow"],
    )


def test_resolve_profile_unknown_falls_back_to_process_uri() -> None:
    selected, uri = constants.resolve_profile("nonsense")
    assert selected == "nonsense"
    assert uri == constants.PROFILE_URIS["process"]


def test_is_web_id() -> None:
    assert constants.is_web_id("https://example.org/x")
    assert constants.is_web_id("http://example.org/x")
    assert constants.is_web_id("urn:uuid:1234")
    assert constants.is_web_id("file:///tmp/x")
    assert not constants.is_web_id("#local")
    assert not constants.is_web_id("relative/path")


def test_completed_or_failed() -> None:
    assert constants.completed_or_failed(True) == constants.ACTION_STATUS_COMPLETED
    assert constants.completed_or_failed(False) == constants.ACTION_STATUS_FAILED
    assert constants.ACTION_STATUS_COMPLETED == "http://schema.org/CompletedActionStatus"
    assert constants.ACTION_STATUS_FAILED == "http://schema.org/FailedActionStatus"


def test_completed_or_active() -> None:
    assert constants.completed_or_active(True) == constants.ACTION_STATUS_COMPLETED
    assert constants.completed_or_active(False) == constants.ACTION_STATUS_ACTIVE
    assert constants.ACTION_STATUS_ACTIVE == "http://schema.org/ActiveActionStatus"


def test_dirty_effect_checkpoint_completed_clears() -> None:
    assert constants.dirty_effect("crate.checkpoint.completed") == "clear"


def test_dirty_effect_checkpoint_started_preserves() -> None:
    assert constants.dirty_effect("crate.checkpoint.started") == "preserve"


def test_dirty_effect_validation_preserves() -> None:
    assert constants.dirty_effect("crate.validation.started") == "preserve"
    assert constants.dirty_effect("crate.validation.completed") == "preserve"


def test_dirty_effect_failures_set() -> None:
    assert constants.dirty_effect("crate.checkpoint.failed") == "set"
    assert constants.dirty_effect("crate.validation.failed") == "set"


def test_dirty_effect_materializing_event_sets() -> None:
    assert constants.dirty_effect("execution.command.completed") == "set"
    assert constants.dirty_effect("file.created") == "set"


def test_profile_choices() -> None:
    assert constants.PROFILE_CHOICES == ("process", "provenance", "workflow", "auto")


def test_workflow_like_profiles() -> None:
    assert constants.WORKFLOW_LIKE_PROFILES == frozenset({"workflow", "provenance"})


def test_dependency_manifests_excludes_containers() -> None:
    assert "Dockerfile" not in constants.DEPENDENCY_MANIFESTS
    assert "Containerfile" not in constants.DEPENDENCY_MANIFESTS
    assert "requirements.txt" in constants.DEPENDENCY_MANIFESTS
    assert "pyproject.toml" in constants.DEPENDENCY_MANIFESTS
    assert "renv.lock" in constants.DEPENDENCY_MANIFESTS
    assert len(constants.DEPENDENCY_MANIFESTS) == 10


def test_container_manifests() -> None:
    assert constants.CONTAINER_MANIFESTS == frozenset({"Dockerfile", "Containerfile"})


def test_deterministic_zip_epoch() -> None:
    assert constants.DETERMINISTIC_ZIP_EPOCH == (2026, 6, 17, 0, 0, 0)


def test_workflow_ro_crate_uri() -> None:
    assert (
        constants.WORKFLOW_RO_CRATE_URI
        == "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
    )
