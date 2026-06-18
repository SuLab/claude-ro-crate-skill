from __future__ import annotations

from tests.e2e.scenarios._common import (
    PROCESS_URI,
    PROVENANCE_URI,
    WORKFLOW_URI,
)
from tests.e2e.spec import ScenarioSpec, SeedFile

_RUN_PROFILE_URIS = (PROCESS_URI, WORKFLOW_URI, PROVENANCE_URI)


def _check_any_run_profile(graph: list, result) -> None:
    # Natural scenarios leave HOW to the agent; just require a valid run-profile crate.
    root = next((e for e in graph if e.get("@id") == "./"), {})
    conforms = root.get("conformsTo", [])
    conforms = [conforms] if isinstance(conforms, dict) else conforms
    ids = [c.get("@id") for c in conforms]
    assert any(u in ids for u in _RUN_PROFILE_URIS), f"root conformsTo no run profile: {ids}"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="nat-process",
        area="natural",
        seed_files=(SeedFile("data.csv", "id,score\n1,10\n2,20\n3,30\n"),),
        coverage_tags=frozenset({"feature:natural-language"}),
        check=_check_any_run_profile,
        # No STRICT_PREAMBLE: a realistic task; the agent decides how to use the skill.
        prompt=(
            "You are working in this project. Count the number of data rows in data.csv "
            "(excluding the header) and write the count to rows.txt. Capture full provenance "
            "of your work using the ro-crate-run skill: start a run, declare data.csv as an "
            "input and rows.txt as an output, run the counting command through rcr so it is "
            "recorded, then checkpoint the crate. Use the bundled rcr CLI for all provenance."
        ),
    ),
    ScenarioSpec(
        name="nat-multistep",
        area="natural",
        seed_files=(SeedFile("nums.txt", "3\n1\n2\n"),),
        coverage_tags=frozenset(set()),
        check=_check_any_run_profile,
        prompt=(
            "You are working in this project. Using the ro-crate-run skill to capture "
            "provenance, perform a small two-step pipeline on nums.txt: first sort the numbers "
            "into sorted.txt, then sum them into total.txt. Record each command through rcr, "
            "declare the inputs and outputs, and checkpoint the crate when done. Use the bundled "
            "rcr CLI for all provenance capture."
        ),
    ),
]
