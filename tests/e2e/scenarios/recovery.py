from __future__ import annotations

import json

from tests.e2e.scenarios._common import PROCESS_URI, STRICT_PREAMBLE, prescriptive_prompt
from tests.e2e.spec import ScenarioSpec


def _journal(result) -> list[dict]:
    p = result.workdir / ".ro-crate-run" / "events.ndjson"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _check_aborted(graph: list, result) -> None:
    assert any(e.get("event_type") == "run.aborted" for e in _journal(result)), \
        "no run.aborted event in journal"


def _check_stale(graph: list, result) -> None:
    warnings = (result.validate_json or {}).get("warnings", [])
    assert any(w.get("code") == "crate_stale" for w in warnings), \
        f"expected crate_stale warning; got {[w.get('code') for w in warnings]}"


def _check_recovered(graph: list, result) -> None:
    events = _journal(result)
    assert any(str(e.get("event_type", "")).startswith("journal.repair") for e in events), \
        "no journal.repair.* event after abandoned-command recovery"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="rec-abort",
        area="recovery",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"cmd:abort", "feature:abort", "cmd:status"}),
        check=_check_aborted,
        prompt=prescriptive_prompt(
            "Start a run, do a little work, then abort it.",
            [
                'rcr start "Aborted run" --mode advisory --profile process',
                "rcr run -- python3 -c \"print('partial work')\"",
                "rcr checkpoint",
                "rcr status",
                'rcr abort',
            ],
        ),
    ),
    ScenarioSpec(
        name="rec-stale",
        area="recovery",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"feature:stale-checkpoint"}),
        check=_check_stale,
        prompt=prescriptive_prompt(
            "Checkpoint, then record more provenance so the crate becomes stale.",
            [
                'rcr start "Stale crate" --mode advisory --profile process',
                "rcr run -- python3 -c \"print('one')\"",
                "rcr checkpoint",
                'rcr note "An observation recorded after the checkpoint" --public',
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="rec-abandoned",
        area="recovery",
        timeout=30,
        skip_crate_battery=True,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"feature:recovery-abandoned"}),
        check=_check_recovered,
        prompt=prescriptive_prompt(
            "Start a run and launch a long-running command (it will be interrupted).",
            [
                'rcr start "Abandoned command" --mode advisory --profile process',
                "rcr run -- python3 -c \"print('quick'); import time; time.sleep(600)\"",
            ],
        ),
    ),
    ScenarioSpec(
        name="rec-utility",
        area="recovery",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:hash", "cmd:inspect", "cmd:status", "cmd:resume",
            "flag:start:--no-checkpoint", "flag:validate:--strict",
        }),
        prompt=prescriptive_prompt(
            "Exercise the read-only / utility commands.",
            [
                'rcr start "Utility commands" --mode advisory --profile process --no-checkpoint',
                'rcr software python3 --version "3.12.3"',
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('x\\n')\"",
                "rcr output out.txt --role result",
                "rcr checkpoint",
                "rcr hash out.txt",
                "rcr inspect",
                "rcr status",
                "rcr resume",
                "rcr validate --strict",
            ],
        ),
    ),
]
