from __future__ import annotations

from tests.e2e.assertions import assert_entity_type, by_type, entities_by_id
from tests.e2e.scenarios._common import (
    PROCESS_URI,
    PROVENANCE_URI,
    STRICT_PREAMBLE,
    WORKFLOW_URI,
    prescriptive_prompt,
)
from tests.e2e.spec import ScenarioSpec, SeedFile

CWL = """cwlVersion: v1.2
class: Workflow
inputs:
  infile: File
outputs:
  outfile:
    type: File
    outputSource: step1/out
steps:
  step1:
    run: echo.cwl
    in:
      in: infile
    out: [out]
"""
ECHO_CWL = """cwlVersion: v1.2
class: CommandLineTool
baseCommand: echo
inputs:
  in: {type: string, inputBinding: {position: 1}}
outputs:
  out: stdout
"""
SNAKEFILE = """rule all:
    input: "out.txt"

rule make:
    output: "out.txt"
    shell: "echo hi > out.txt"
"""
NEXTFLOW = """process FOO {
    script:
    \"\"\"
    echo hi
    \"\"\"
}
"""
GALAXY = (
    '{"a_galaxy_workflow": "true", "name": "wf", '
    '"steps": {"0": {"name": "step0"}, "1": {"name": "step1"}}}'
)


def _has_status(action: dict, needle: str) -> bool:
    st = action.get("actionStatus")
    sid = st.get("@id") if isinstance(st, dict) else st
    return bool(sid) and needle in sid


def _check_proc_minimal(graph: list, result) -> None:
    assert_entity_type(graph, "CreateAction", min_count=1)
    actions = by_type(graph, "CreateAction")
    assert any(a.get("result") for a in actions), "no CreateAction has a result file"
    assert any(a.get("instrument") for a in actions), "no CreateAction has an instrument"
    assert any(e.get("@id", "").startswith("#software/") for e in graph), \
        "no #software/* SoftwareApplication entity"
    assert "./" in entities_by_id(graph)


def _check_proc_multi(graph: list, result) -> None:
    assert_entity_type(graph, "CreateAction", min_count=1)
    assert_entity_type(graph, "UpdateAction", min_count=1)
    creates = by_type(graph, "CreateAction")
    assert any(a.get("object") for a in creates), "no CreateAction with an object (input)"


def _check_proc_failed(graph: list, result) -> None:
    actions = by_type(graph, "Action") + by_type(graph, "CreateAction")
    failed = [a for a in actions if _has_status(a, "Failed")]
    assert failed, f"no action with FailedActionStatus; statuses={[a.get('actionStatus') for a in actions]}"
    assert any(a.get("error") for a in failed), "failed action has no error property"


def _check_proc_delete(graph: list, result) -> None:
    assert_entity_type(graph, "DeleteAction", min_count=1)


def _check_workflow(graph: list, result) -> None:
    assert_entity_type(graph, "ComputationalWorkflow", min_count=1)
    wf = by_type(graph, "ComputationalWorkflow")[0]
    assert wf.get("programmingLanguage"), "workflow missing programmingLanguage"
    root = entities_by_id(graph).get("./", {})
    assert root.get("mainEntity"), "root missing mainEntity"


def _check_wf_cwl(graph: list, result) -> None:
    _check_workflow(graph, result)
    assert_entity_type(graph, "FormalParameter", min_count=1)
    assert_entity_type(graph, "PropertyValue", min_count=1)
    pvs = by_type(graph, "PropertyValue")
    assert any(p.get("exampleOfWork") for p in pvs), "no PropertyValue links exampleOfWork"


def _check_wf_steps(graph: list, result) -> None:
    _check_workflow(graph, result)
    assert_entity_type(graph, "HowToStep", min_count=1)


def _check_provenance(graph: list, result) -> None:
    assert_entity_type(graph, "HowToStep", min_count=1)
    assert_entity_type(graph, "ControlAction", min_count=1)
    steps = by_type(graph, "HowToStep")
    assert any(s.get("workExample") for s in steps), "no HowToStep with workExample"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="proc-minimal",
        area="profiles",
        expected_profile_uri=PROCESS_URI,
        seed_files=(SeedFile("data.csv", "a,b\n1,2\n3,4\n"),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:start", "cmd:software", "cmd:input", "cmd:run", "cmd:output",
            "cmd:checkpoint", "cmd:validate",
            "flag:start:--mode", "flag:start:--profile", "flag:software:--version",
            "flag:input:--role", "flag:input:--description",
            "flag:output:--role", "flag:output:--required", "flag:run:--outputs",
            "flag:validate:--json",
            "entity:CreateAction", "entity:File", "entity:SoftwareApplication",
            "entity:Person", "entity:Dataset", "entity:Profile",
            "prop:action:object", "prop:action:result", "prop:action:instrument",
            "prop:action:agent", "prop:action:actionStatus", "prop:file:sha256",
            "profile:process", "mode:advisory",
        }),
        check=_check_proc_minimal,
        prompt=prescriptive_prompt(
            "Capture provenance of counting rows in a CSV.",
            [
                'rcr start "Process minimal" --mode advisory --profile process',
                'rcr software python3 --version "Python 3.12.3"',
                'rcr input data.csv --role dataset --description "input csv"',
                "rcr run --outputs rows.txt -- python3 -c "
                "\"open('rows.txt','w').write(str(sum(1 for _ in open('data.csv'))))\"",
                'rcr output rows.txt --role result --required',
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="proc-multi",
        area="profiles",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "entity:UpdateAction", "flag:run:--inputs", "mode:monitored",
        }),
        check=_check_proc_multi,
        prompt=prescriptive_prompt(
            "Capture provenance of a two-step transform with an in-place update.",
            [
                'rcr start "Process multi" --mode monitored --profile process',
                "rcr run --outputs a.txt -- python3 -c \"open('a.txt','w').write('1\\n')\"",
                "rcr input a.txt --role intermediate",
                "rcr output b.txt --role result --required",
                "rcr run --inputs a.txt --outputs b.txt -- python3 -c "
                "\"open('b.txt','w').write(open('a.txt').read()+'2\\n')\"",
                "rcr run --inputs a.txt --outputs a.txt -- python3 -c "
                "\"open('a.txt','a').write('3\\n')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="proc-failed",
        area="profiles",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "entity:Action", "prop:action:error",
        }),
        check=_check_proc_failed,
        prompt=prescriptive_prompt(
            "Capture provenance of a command that fails. The non-zero exit is expected; "
            "still run every command including checkpoint and validate.",
            [
                'rcr start "Process failed" --mode advisory --profile process',
                "rcr run -- python3 -c \"import sys; sys.exit(3)\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="proc-delete",
        area="profiles",
        expected_profile_uri=PROCESS_URI,
        seed_files=(SeedFile("victim.txt", "delete me\n"),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "entity:DeleteAction",
        }),
        check=_check_proc_delete,
        prompt=prescriptive_prompt(
            "Capture provenance of deleting a file.",
            [
                'rcr start "Process delete" --mode advisory --profile process',
                "rcr input victim.txt --role temp",
                "rcr run --inputs victim.txt -- rm victim.txt",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="wf-cwl",
        area="profiles",
        expected_profile_uri=WORKFLOW_URI,
        seed_files=(
            SeedFile("workflow.cwl", CWL),
            SeedFile("echo.cwl", ECHO_CWL),
            SeedFile("data.txt", "hello\n"),
        ),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:parameter", "flag:parameter:--formal-parameter", "flag:parameter:--type",
            "flag:software:--type",
            "entity:ComputationalWorkflow", "entity:FormalParameter", "entity:PropertyValue",
            "prop:workflow:programmingLanguage", "prop:workflow:mainEntity",
            "prop:file:exampleOfWork", "profile:workflow",
        }),
        check=_check_wf_cwl,
        prompt=prescriptive_prompt(
            "Capture provenance of running a CWL workflow.",
            [
                'rcr start "CWL workflow" --mode advisory --profile workflow',
                'rcr software cwltool --version "3.1.0" --type CommandLineTool',
                "rcr input workflow.cwl --role workflow-definition",
                "rcr input data.txt --role dataset",
                "rcr parameter infile data.txt --formal-parameter infile --type File",
                "rcr run --inputs data.txt --outputs result.txt -- python3 -c "
                "\"open('result.txt','w').write(open('data.txt').read().upper())\"",
                "rcr output result.txt --role result --required",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="wf-snakemake",
        area="profiles",
        expected_profile_uri=WORKFLOW_URI,
        seed_files=(SeedFile("Snakefile", SNAKEFILE),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "feature:auto-profile", "entity:HowToStep",
            "cmd:checkpoint", "flag:checkpoint:--profile",
        }),
        check=_check_wf_steps,
        prompt=prescriptive_prompt(
            "Capture provenance of a Snakemake workflow; let the profile be auto-selected.",
            [
                'rcr start "Snakemake auto" --mode advisory --profile auto',
                'rcr software snakemake --version "7.32.0"',
                "rcr input Snakefile --role workflow-definition",
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('hi\\n')\"",
                "rcr output out.txt --role result --required",
                "rcr checkpoint --profile auto",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="wf-nextflow",
        area="profiles",
        expected_profile_uri=WORKFLOW_URI,
        seed_files=(SeedFile("main.nf", NEXTFLOW),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset(set()),
        check=_check_workflow,
        prompt=prescriptive_prompt(
            "Capture provenance of a Nextflow workflow.",
            [
                'rcr start "Nextflow workflow" --mode advisory --profile workflow',
                'rcr software nextflow --version "23.10.0"',
                "rcr input main.nf --role workflow-definition",
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('hi\\n')\"",
                "rcr output out.txt --role result --required",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="wf-galaxy",
        area="profiles",
        expected_profile_uri=WORKFLOW_URI,
        seed_files=(SeedFile("wf.ga", GALAXY),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset(set()),
        check=_check_workflow,
        prompt=prescriptive_prompt(
            "Capture provenance of a Galaxy workflow.",
            [
                'rcr start "Galaxy workflow" --mode advisory --profile workflow',
                'rcr software galaxy --version "23.1"',
                "rcr input wf.ga --role workflow-definition",
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('hi\\n')\"",
                "rcr output out.txt --role result --required",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="prov-two-step",
        area="profiles",
        expected_profile_uri=PROVENANCE_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:step", "flag:step:start", "flag:step:end", "flag:run:--step",
            "entity:HowToStep", "entity:ControlAction", "prop:step:workExample",
            "profile:provenance",
        }),
        check=_check_provenance,
        prompt=prescriptive_prompt(
            "Capture provenance of a two-step pipeline with explicit steps.",
            [
                'rcr start "Provenance two-step" --mode advisory --profile provenance',
                'rcr step start s1 --description "extract"',
                "rcr run --step s1 --outputs a.txt -- python3 -c \"open('a.txt','w').write('1\\n')\"",
                "rcr step end s1 --status completed",
                'rcr step start s2 --description "transform"',
                "rcr run --step s2 --inputs a.txt --outputs b.txt -- python3 -c "
                "\"open('b.txt','w').write(open('a.txt').read()+'2\\n')\"",
                "rcr step end s2 --status completed",
                "rcr output b.txt --role result --required",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="prov-run-step",
        area="profiles",
        expected_profile_uri=PROVENANCE_URI,
        seed_files=(
            SeedFile("pipeline.cwl", CWL),
            SeedFile("echo.cwl", ECHO_CWL),
            SeedFile("in.txt", "data\n"),
        ),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset(set()),
        check=_check_provenance,
        prompt=prescriptive_prompt(
            "Capture provenance of a CWL pipeline with one executed step; auto-select profile.",
            [
                'rcr start "Provenance auto" --mode advisory --profile auto',
                'rcr software cwltool --version "3.1.0"',
                "rcr input pipeline.cwl --role workflow-definition",
                'rcr step start s1 --description "run"',
                "rcr run --step s1 --inputs in.txt --outputs out.txt -- python3 -c "
                "\"open('out.txt','w').write(open('in.txt').read())\"",
                "rcr step end s1 --status completed",
                "rcr output out.txt --role result --required",
                "rcr checkpoint --profile auto",
                "rcr validate --json",
            ],
        ),
    ),
]
