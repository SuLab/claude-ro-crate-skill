from __future__ import annotations

from tests.e2e.assertions import by_type, entities_by_id
from tests.e2e.scenarios._common import (
    PROCESS_URI,
    STRICT_PREAMBLE,
    WORKFLOW_URI,
    prescriptive_prompt,
)
from tests.e2e.spec import ScenarioSpec, SeedFile


def _has_prop_value(graph: list, name: str) -> bool:
    for e in graph:
        t = e.get("@type")
        if "PropertyValue" in ([t] if isinstance(t, str) else (t or [])) and e.get("name") == name:
            return True
    return False


def _check_io_flags(graph: list, result) -> None:
    # All declared files become File entities; copied ones land in hasPart.
    assert len(by_type(graph, "File")) >= 4, "expected several File entities"


def _check_notes_decisions(graph: list, result) -> None:
    # Public note + public decision -> CreativeWork entities (license/descriptor are also
    # CreativeWork, so just assert a decision with rationale is present).
    assert any(e.get("description") and str(e.get("@id", "")).startswith("#decision") for e in graph), \
        "no decision entity with rationale description"


def _check_phase_open_warning(graph: list, result) -> None:
    warnings = (result.validate_json or {}).get("warnings", [])
    assert any(w.get("code", "").startswith("open_phase") for w in warnings), \
        f"expected an open_phase warning; got {[w.get('code') for w in warnings]}"


def _check_git(graph: list, result) -> None:
    git = entities_by_id(graph).get("#git/state")
    assert git is not None, "no #git/state entity"
    assert _has_prop_value(graph, "branch"), "no git branch PropertyValue"
    assert _has_prop_value(graph, "dirty"), "no git dirty PropertyValue"


def _check_journal_embedded(graph: list, result) -> None:
    ids = {e.get("@id") for e in graph}
    assert "events.ndjson" in ids, "event journal File entity not embedded in crate"


def _check_params_container(graph: list, result) -> None:
    assert by_type(graph, "ParameterConnection"), "no ParameterConnection entity"
    assert by_type(graph, "ContainerImage"), "no ContainerImage entity"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="field-io-flags",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        seed_files=(
            SeedFile("local_in.txt", "local input\n"),
            SeedFile("copy_me.txt", "copy this\n"),
            SeedFile("ref_me.txt", "reference this\n"),
        ),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "flag:input:--required", "flag:input:--public", "flag:input:--private",
            "flag:input:--existence", "flag:input:--copy", "flag:input:--reference",
            "flag:output:--description", "flag:output:--public", "flag:output:--private",
            "flag:output:--existence", "flag:output:--copy", "flag:output:--reference",
            "existence:observed local", "existence:observed remote", "existence:generated",
            "existence:expected", "existence:missing", "existence:declared-only",
            "policy:copy", "policy:reference", "policy:out-of-root-reference",
        }),
        check=_check_io_flags,
        prompt=prescriptive_prompt(
            "Declare inputs and outputs covering every flag and existence value.",
            [
                'rcr start "IO flags" --mode advisory --profile process',
                'rcr input local_in.txt --role dataset --existence "observed local" --required --private',
                "rcr input copy_me.txt --role aux --copy --public",
                "rcr input ref_me.txt --role aux --reference",
                'rcr input /etc/hostname --role host --reference --existence "observed local"',
                'rcr input remote_data.csv --role remote --existence "observed remote"',
                'rcr input maybe.txt --role optional --existence "declared-only"',
                'rcr output out.txt --role result --description "the result" --existence generated --required --copy',
                'rcr output future.txt --role pending --existence expected --private',
                'rcr output gone.txt --role gone --existence missing --reference',
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('done\\n')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-notes-decisions",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:note", "cmd:decision", "cmd:accept", "cmd:reject",
            "flag:note:--public", "flag:note:--private",
            "flag:decision:--rationale", "flag:decision:--public", "flag:decision:--private",
            "entity:CreativeWork", "prop:decision:rationale",
        }),
        check=_check_notes_decisions,
        prompt=prescriptive_prompt(
            "Record observations and decisions, public and private.",
            [
                'rcr start "Notes and decisions" --mode advisory --profile process',
                'rcr note "Public observation about the data" --public',
                'rcr note "Private internal note" --private',
                'rcr decision "Chose method A" --rationale "A is simpler and faster" --public',
                'rcr decision "Internal tradeoff" --rationale "kept for the record" --private',
                "rcr run -- python3 -c \"print('work')\"",
                'rcr accept "Result looks correct"',
                'rcr reject "Second attempt was wrong"',
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-phase",
        area="fields",
        expected_profile_uri=WORKFLOW_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:phase", "feature:open-phase-warning",
        }),
        expect_validation_status=("passed", "warning"),
        check=_check_phase_open_warning,
        prompt=prescriptive_prompt(
            "Structure work into phases and leave the last phase open.",
            [
                'rcr start "Phased work" --mode advisory --profile auto',
                "rcr phase setup",
                "rcr run -- python3 -c \"print('setup')\"",
                "rcr phase analysis --complete-current",
                "rcr run -- python3 -c \"print('analyze')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-git-deps",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        seed_files=(
            SeedFile("requirements.txt", "requests==2.31.0\nnumpy==1.26.0\n"),
            SeedFile("README.md", "# project\n"),
        ),
        git_commit=True,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:config", "policy:lockfile-scan", "policy:include_git_diff",
            "prop:git:branch", "prop:git:dirty", "entity:Thing",
        }),
        check=_check_git,
        prompt=prescriptive_prompt(
            "Capture git state (with a dirty working tree) and dependency lockfiles.",
            [
                'rcr start "Git and deps" --mode advisory --profile process',
                "rcr config file_policy.include_git_diff always",
                'rcr software python3 --version "3.12.3"',
                "rcr run -- python3 -c \"open('README.md','a').write('dirty change\\n')\"",
                "rcr output README.md --role doc",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-config-journal",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "policy:include_event_journal",
        }),
        check=_check_journal_embedded,
        prompt=prescriptive_prompt(
            "Enable embedding the event journal in the crate.",
            [
                'rcr start "Embedded journal" --mode advisory --profile process',
                "rcr config file_policy.include_event_journal true",
                "rcr run -- python3 -c \"print('hi')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-params-container",
        area="fields",
        expected_profile_uri=WORKFLOW_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "entity:ParameterConnection", "entity:ContainerImage",
        }),
        check=_check_params_container,
        prompt=prescriptive_prompt(
            "Declare a containerized step with connected parameters.",
            [
                'rcr start "Params and container" --mode advisory --profile workflow',
                'rcr software python3 --version "3.12.3"',
                "rcr container docker.io/library/python:3.12 --digest sha256:deadbeef",
                'rcr parameter raw raw.csv --formal-parameter "#param/raw" --type File',
                'rcr parameter clean clean.csv --formal-parameter "#param/clean" --type File --connect-from "#param/raw" --connect-to "#param/clean"',
                "rcr run --outputs clean.csv -- python3 -c \"open('clean.csv','w').write('ok\\n')\"",
                "rcr output clean.csv --role result --required",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
]
