from __future__ import annotations

from ro_crate_run.constants import EVENT_TYPES


def test_event_types_registry_includes_new_families() -> None:
    for name in [
        "run.config.updated",
        "run.aborted",
        "human.accepted_result",
        "human.rejected_result",
        "workflow.step.identified",
    ]:
        assert name in EVENT_TYPES
