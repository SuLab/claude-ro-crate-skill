"""E2E scenarios for the agent-action materialization families (SPEC §16).

Unlike the prescriptive ``profiles`` scenarios (which feed a verbatim rcr command
list), these drive the agent to take its OWN actions — run a raw Bash command, edit a
file directly, dispatch a subagent — then capture + checkpoint, and assert the
corresponding action family is present in the emitted crate ``@graph``.

These require the live ``claude`` CLI and are NOT run as part of the unit gate; this
module only needs to import/parse cleanly and register in ``ALL_SCENARIOS``.
"""
from __future__ import annotations

import json

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
    # Two raw commands -> structured agent work -> synthesized workflow as mainEntity.
    root = entities_by_id(graph).get("./", {})
    assert root.get("mainEntity"), "root missing mainEntity (no synthesized workflow)"


def _journal_events(result) -> list:
    p = result.workdir / ".ro-crate-run" / "events.ndjson"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _check_auto_start(graph: list, result) -> None:
    # The run was bootstrapped by a hook (RCR_AUTO_START), not by an explicit `rcr start`.
    events = _journal_events(result)
    started = [e for e in events if e.get("event_type") == "run.started"]
    assert started, "no run.started — auto-start did not bootstrap a run"
    assert any(
        (e.get("source") or {}).get("kind") == "claude_hook" for e in started
    ), "run.started was not emitted by a hook (auto-start path not taken)"
    # And the agent's edit was still materialized.
    assert _by_prefix(graph, "#file-action/"), "auto-started run captured no file edits"


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


def _check_surfaces(graph: list, result) -> None:
    # Read/Glob (non-Bash tools) -> #tool-use Action; the automatic tool batches ->
    # #housekeeping Action; editing an EXISTING file -> UpdateAction (the modify path).
    tu = _by_prefix(graph, "#tool-use/")
    assert tu, "no #tool-use/* Action — non-Bash tool activity (Read/Glob) not captured"
    assert all("Action" in _types(e) for e in tu), f"#tool-use not Actions: {[_types(e) for e in tu]}"
    hk = _by_prefix(graph, "#housekeeping/")
    assert hk, "no #housekeeping/* Action — tool.batch.completed not captured"
    fa = _by_prefix(graph, "#file-action/")
    assert any("UpdateAction" in _types(e) for e in fa), \
        f"no UpdateAction from the Edit of an existing file; types={[_types(e) for e in fa]}"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="agent-raw-bash",
        area="natural",
        seed_files=(SeedFile("data.csv", "a,b\n1,2\n3,4\n"),),
        coverage_tags=frozenset({
            "feature:raw-bash-action", "entity:CreateAction",
        }),
        check=_check_raw_bash,
        prompt=(
            "You are capturing provenance with the ro-crate-run skill. Steps, in order:\n"
            "1. Run: rcr start \"Agent raw bash\" --mode advisory --profile auto\n"
            "2. Run: rcr input data.csv --role dataset\n"
            "3. Using the Bash tool, run this shell command DIRECTLY (do NOT wrap it in "
            "rcr run): wc -l data.csv\n"
            "4. Using the Bash tool, run this shell command DIRECTLY (do NOT wrap it in "
            "rcr run): head -1 data.csv\n"
            "5. Run: rcr checkpoint\n"
            "6. Run: rcr validate --json\n"
            "The two raw shell commands are the point — run them directly via the Bash tool."
        ),
    ),
    ScenarioSpec(
        name="agent-auto-start",
        area="natural",
        env={"RCR_AUTO_START": "1"},
        seed_files=(SeedFile("data.txt", "hello\n"),),
        coverage_tags=frozenset({"feature:auto-start"}),
        check=_check_auto_start,
        prompt=(
            "Provenance capture is enabled automatically for this session — do NOT run "
            "'rcr start'. Using the Edit tool, append a line 'world' to data.txt. Then "
            "finalize the provenance crate by running: rcr checkpoint, then "
            "rcr validate --json. Use the bundled rcr CLI for those two commands."
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
        name="agent-surfaces",
        area="natural",
        seed_files=(
            SeedFile("notes.txt", "read me\n"),
            SeedFile("edit_me.txt", "the old value\n"),
        ),
        coverage_tags=frozenset({
            "feature:tool-use-action", "feature:housekeeping-action",
            "feature:agent-file-update",
        }),
        check=_check_surfaces,
        prompt=(
            "You are capturing provenance with the ro-crate-run skill. Steps, in order:\n"
            "1. Run: rcr start \"Agent surfaces\" --mode advisory --profile auto\n"
            "2. Use the Read tool to read notes.txt (do NOT use cat/Bash).\n"
            "3. Use the Glob tool to list the *.txt files.\n"
            "4. Use the Edit tool to change the word 'old' to 'new' in the EXISTING file "
            "edit_me.txt (an in-place modification — use Edit, not Write).\n"
            "5. Run: rcr checkpoint\n"
            "6. Run: rcr validate --json\n"
            "Using the Read/Glob/Edit tools directly is the point of this task."
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
