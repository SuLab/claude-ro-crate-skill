"""E2E scenarios for the agent-action materialization families (SPEC §16).

Unlike the prescriptive ``profiles`` scenarios (which feed a verbatim rcr command
list), these drive the agent to take its OWN actions — run a raw Bash command, edit a
file directly, dispatch a subagent — then capture + checkpoint, and assert the
corresponding action family is present in the emitted crate ``@graph``.

These require the live ``claude`` CLI and are NOT run as part of the unit gate; this
module only needs to import/parse cleanly and register in ``ALL_SCENARIOS``.
"""
from __future__ import annotations

from tests.e2e.assertions import by_type, entities_by_id
from tests.e2e.scenarios._common import STRICT_PREAMBLE, prescriptive_prompt
from tests.e2e.spec import ScenarioSpec, SeedFile


def _by_prefix(graph: list, prefix: str) -> list:
    return [e for e in graph if str(e.get("@id", "")).startswith(prefix)]


def _types(entity: dict) -> list:
    t = entity.get("@type")
    return [t] if isinstance(t, str) else (t or [])


def _check_raw_bash(graph: list, result) -> None:
    raw = _by_prefix(graph, "#raw-command/")
    assert raw, "no #raw-command/* CreateAction (raw Bash command not captured)"
    assert any("CreateAction" in _types(e) for e in raw), \
        f"#raw-command present but not a CreateAction: {[_types(e) for e in raw]}"
    # The synthesized agent-actions workflow should be the crate's mainEntity.
    root = entities_by_id(graph).get("./", {})
    assert root.get("mainEntity"), "root missing mainEntity (no synthesized workflow)"


def _check_file_edit(graph: list, result) -> None:
    actions = _by_prefix(graph, "#file-action/")
    assert actions, "no #file-action/* entity (agent file edit not captured)"
    edit_types = {t for e in actions for t in _types(e)}
    assert edit_types & {"CreateAction", "UpdateAction"}, \
        f"file action has unexpected types: {edit_types}"
    for fa in actions:
        assert fa.get("result") or fa.get("object"), \
            "file action missing result/object File reference"


def _check_subagent(graph: list, result) -> None:
    subagents = _by_prefix(graph, "#subagent/")
    assert subagents, "no #subagent/* OrganizeAction (subagent dispatch not captured)"
    assert any("OrganizeAction" in _types(e) for e in subagents), \
        f"#subagent present but not an OrganizeAction: {[_types(e) for e in subagents]}"


def _check_assess(graph: list, result) -> None:
    results = _by_prefix(graph, "#result/")
    assert results, "no #result/* AssessAction (human accept/reject not captured)"
    assess = by_type(graph, "AssessAction")
    assert assess, "no AssessAction entity in graph"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="agent-raw-bash",
        area="natural",
        seed_files=(SeedFile("data.csv", "a,b\n1,2\n3,4\n"),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "feature:raw-bash-action", "feature:auto-start",
            "entity:CreateAction",
        }),
        check=_check_raw_bash,
        prompt=prescriptive_prompt(
            "Capture provenance of inspecting a CSV with a raw shell command. Run the "
            "wc command DIRECTLY via the Bash tool (do NOT wrap it in rcr run); rcr will "
            "still record it as a raw-command action.",
            [
                'rcr start "Agent raw bash" --mode advisory --profile auto',
                "rcr input data.csv --role dataset",
                "wc -l data.csv",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="agent-file-edit",
        area="natural",
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "feature:agent-file-edits",
            "entity:UpdateAction",
        }),
        check=_check_file_edit,
        prompt=prescriptive_prompt(
            "Capture provenance of the agent authoring a small script. Create the file "
            "summarize.py using the Write/Edit tool directly (not via a shell command).",
            [
                'rcr start "Agent file edit" --mode advisory --profile auto',
                "Write summarize.py with the contents: print('rows summarized')",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="agent-subagent",
        area="natural",
        seed_files=(SeedFile("notes.txt", "find the parser entrypoint\n"),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "feature:subagent-action",
            "entity:OrganizeAction",
        }),
        check=_check_subagent,
        prompt=prescriptive_prompt(
            "Capture provenance of dispatching a subagent. Use the Task tool to dispatch "
            "one subagent that reads notes.txt and reports its single line; rcr records "
            "the dispatch as an OrganizeAction.",
            [
                'rcr start "Agent subagent" --mode advisory --profile auto',
                "Dispatch a Task subagent to read notes.txt and report its contents",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="agent-assess",
        area="natural",
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "entity:AssessAction",
        }),
        check=_check_assess,
        prompt=prescriptive_prompt(
            "Capture provenance of a human assessing a generated result.",
            [
                'rcr start "Agent assess" --mode advisory --profile auto',
                "rcr run --outputs out.txt -- python3 -c "
                "\"open('out.txt','w').write('done\\n')\"",
                'rcr accept "Output looks correct"',
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
]
