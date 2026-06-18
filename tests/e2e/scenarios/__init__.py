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

# Prepended (via --append-system-prompt) to prescriptive scenarios so the agent runs the
# listed rcr commands verbatim, making the captured provenance deterministic.
STRICT_PREAMBLE = (
    "You are capturing provenance with the ro-crate-run skill. Run EXACTLY the rcr "
    "commands listed in the user message, in order, verbatim. Do not add, skip, "
    "reorder, or substitute commands. Use the bundled rcr CLI. When a step says to "
    "create a file, create it. After the last command, stop."
)

PROCESS_URI = "https://w3id.org/ro/wfrun/process/0.5"
WORKFLOW_URI = "https://w3id.org/ro/wfrun/workflow/0.5"
PROVENANCE_URI = "https://w3id.org/ro/wfrun/provenance/0.5"

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
