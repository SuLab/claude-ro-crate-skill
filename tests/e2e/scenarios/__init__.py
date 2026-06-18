from __future__ import annotations

from tests.e2e.scenarios import (
    admin,
    enforced,
    fields,
    natural,
    privacy,
    profiles,
    recovery,
)
from tests.e2e.scenarios._common import (
    PROCESS_URI,
    PROVENANCE_URI,
    STRICT_PREAMBLE,
    WORKFLOW_URI,
)

__all__ = [
    "ALL_SCENARIOS",
    "PROCESS_URI",
    "PROVENANCE_URI",
    "STRICT_PREAMBLE",
    "WORKFLOW_URI",
    "by_area",
    "by_name",
]

ALL_SCENARIOS = (
    profiles.SCENARIOS
    + fields.SCENARIOS
    + admin.SCENARIOS
    + enforced.SCENARIOS
    + recovery.SCENARIOS
    + privacy.SCENARIOS
    + natural.SCENARIOS
)


def by_name(name: str):
    for s in ALL_SCENARIOS:
        if s.name == name:
            return s
    raise KeyError(name)


def by_area(area: str) -> list:
    return [s for s in ALL_SCENARIOS if s.area == area]
