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


def _types(entity: dict) -> list:
    t = entity.get("@type")
    return t if isinstance(t, list) else [t]


def _file_sha256(entity: dict, graph: list | None = None) -> str | None:
    # rcr records the digest as an identifier PropertyValue (propertyID 'sha256').
    # Per RO-Crate 1.2 (no anonymous inlining) the PropertyValue is a top-level
    # #embedded/* node and the File's identifier is a {"@id": ...} reference, so
    # resolve the reference against the graph before reading the value.
    by_id = {e.get("@id"): e for e in (graph or [])}
    ident = entity.get("identifier")
    for cand in (ident if isinstance(ident, list) else [ident]):
        if isinstance(cand, dict) and set(cand.keys()) == {"@id"}:
            cand = by_id.get(cand["@id"], cand)
        if isinstance(cand, dict) and cand.get("propertyID") == "sha256":
            v = str(cand.get("value", ""))
            if len(v) == 64:
                return v
    return None

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


_ACTION_TYPES = (
    "Action", "CreateAction", "UpdateAction", "DeleteAction",
    "ControlAction", "OrganizeAction", "AssessAction",
)


def _id_refs(value) -> list:  # type: ignore[no-untyped-def]
    # Collect the @id of every {"@id": ...} reference in a scalar-or-list property value.
    out: list = []
    for cand in (value if isinstance(value, list) else [value]):
        if isinstance(cand, dict) and cand.get("@id"):
            out.append(cand["@id"])
    return out


def _is_action(entity: dict) -> bool:
    return any(t in _types(entity) for t in _ACTION_TYPES)


def _check_proc_minimal(graph: list, result) -> None:
    ids = entities_by_id(graph)
    assert "./" in ids, "missing root data entity"
    assert "Dataset" in _types(ids["./"]), f"root is not a Dataset: {_types(ids['./'])}"

    # A CreateAction whose result/instrument/agent all resolve, with a terminal status.
    assert_entity_type(graph, "CreateAction", min_count=1)
    actions = by_type(graph, "CreateAction")
    assert any(a.get("result") for a in actions), "no CreateAction has a result file"
    instruments = [a.get("instrument") for a in actions if a.get("instrument")]
    assert instruments, "no CreateAction has an instrument"
    assert all(i.get("@id") in ids and "SoftwareApplication" in _types(ids[i["@id"]])
               for i in instruments), "instrument does not resolve to a SoftwareApplication"
    person_ids = {e["@id"] for e in by_type(graph, "Person")}
    assert person_ids, "no Person actor entity (human provenance missing)"
    agents = [a.get("agent") for a in actions if a.get("agent")]
    assert agents and any(a.get("@id") in person_ids for a in agents), \
        "no CreateAction is agented to a Person"
    assert any(_has_status(a, "Completed") for a in actions), \
        "no CreateAction reports CompletedActionStatus"

    # SoftwareApplication with a recorded version.
    sw = [e for e in graph if str(e.get("@id", "")).startswith("#software/")]
    assert sw and any(e.get("softwareVersion") or e.get("version") for e in sw), \
        "no #software/* SoftwareApplication with a version"

    # Output File carries a sha256 digest; a Profile entity backs the root conformsTo.
    assert any(_file_sha256(f, graph) for f in by_type(graph, "File")), "no File carries a sha256"
    assert by_type(graph, "Profile"), "no Profile entity backing root conformsTo"


def _check_proc_multi(graph: list, result) -> None:
    ids = entities_by_id(graph)
    assert_entity_type(graph, "CreateAction", min_count=1)
    assert_entity_type(graph, "UpdateAction", min_count=1)
    creates = by_type(graph, "CreateAction")
    # prop:action:object — a command's --inputs becomes the action's object, and it resolves.
    objects = [o for a in creates for o in (a.get("object") or [])]
    assert objects, "no CreateAction with an object (input)"
    assert all(o.get("@id") in ids for o in objects), "action object ref does not resolve"
    # In-place modification: an UpdateAction whose object AND result reference the SAME file
    # (the a.txt append). That shared object/result is the defining signature of editing a
    # file in place rather than deriving a new output from a distinct input.
    inplace = []
    for u in by_type(graph, "UpdateAction"):
        shared = {o.get("@id") for o in (u.get("object") or [])} & \
                 {r.get("@id") for r in (u.get("result") or [])}
        shared.discard(None)
        if shared:
            inplace.append((u, shared))
    assert inplace, \
        "no UpdateAction has the same file as both object and result (in-place modification)"
    _, shared = inplace[0]
    assert all(fid in ids for fid in shared), "in-place modified file ref does not resolve"


def _check_proc_failed(graph: list, result) -> None:
    actions = by_type(graph, "Action") + by_type(graph, "CreateAction")
    failed = [a for a in actions if _has_status(a, "Failed")]
    assert failed, f"no action with FailedActionStatus; statuses={[a.get('actionStatus') for a in actions]}"
    assert any(a.get("error") for a in failed), "failed action has no error property"


def _check_proc_delete(graph: list, result) -> None:
    ids = entities_by_id(graph)
    assert_entity_type(graph, "DeleteAction", min_count=1)
    # The DeleteAction must name its victim: object references the deleted file and resolves.
    victims = [d for d in by_type(graph, "DeleteAction")
               if any(o.get("@id") == "victim.txt" for o in (d.get("object") or []))]
    assert victims, "no DeleteAction whose object references the deleted file victim.txt"
    victim = victims[0]
    assert all(o.get("@id") in ids for o in (victim.get("object") or [])), \
        "DeleteAction object ref does not resolve to an emitted entity"
    # A deletion produces nothing: result must be absent or empty.
    assert not victim.get("result"), \
        f"DeleteAction should produce no result, got {victim.get('result')!r}"


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
    # FormalParameters carry their schema shape: an additionalType (the data type) and/or a
    # valueRequired flag, not just a bare @type.
    fps = by_type(graph, "FormalParameter")
    assert any(("additionalType" in p) or ("valueRequired" in p) for p in fps), \
        "no FormalParameter carries additionalType or valueRequired"
    # A concrete File (data.txt) is tied to its abstract slot via exampleOfWork pointing at a
    # FormalParameter — the workflow-profile link from instance data to the declared parameter.
    fp_ids = {p["@id"] for p in fps}
    file_eow = [
        (f["@id"], r) for f in by_type(graph, "File")
        for r in _id_refs(f.get("exampleOfWork")) if r in fp_ids
    ]
    assert file_eow, "no File entity carries exampleOfWork pointing at a FormalParameter"


def _check_wf_steps(graph: list, result) -> None:
    _check_workflow(graph, result)
    assert_entity_type(graph, "HowToStep", min_count=1)


def _check_provenance(graph: list, result) -> None:
    ids = entities_by_id(graph)
    assert_entity_type(graph, "HowToStep", min_count=1)
    assert_entity_type(graph, "ControlAction", min_count=1)
    steps = by_type(graph, "HowToStep")
    assert any(s.get("workExample") for s in steps), "no HowToStep with workExample"
    # A workflow-level action ties the whole run to the workflow: at least one action's
    # instrument must resolve to the ComputationalWorkflow / #workflow/* entity.
    cw_ids = {e["@id"] for e in by_type(graph, "ComputationalWorkflow")}

    def _is_wf_ref(rid: str) -> bool:
        return rid in cw_ids or rid.startswith("#workflow")

    wf_actions = [
        e for e in graph if _is_action(e)
        and any(_is_wf_ref(r) for r in _id_refs(e.get("instrument")))
    ]
    assert wf_actions, "no workflow-level action whose instrument resolves to the workflow"
    for a in wf_actions:
        for r in _id_refs(a.get("instrument")):
            if _is_wf_ref(r):
                assert r in ids, f"workflow instrument {r!r} does not resolve"
    # The step's workExample must resolve to a real SoftwareApplication, not dangle.
    sw_ids = {e["@id"] for e in by_type(graph, "SoftwareApplication")}
    assert any(r in sw_ids for s in steps for r in _id_refs(s.get("workExample"))), \
        "no HowToStep workExample resolves to a SoftwareApplication"
    # Each ControlAction orchestrates a concrete action: its object must resolve to an emitted
    # action entity that itself reports a terminal actionStatus.
    for ca in by_type(graph, "ControlAction"):
        objs = _id_refs(ca.get("object"))
        assert objs, f"ControlAction {ca.get('@id')!r} has no object"
        for oid in objs:
            target = ids.get(oid)
            assert target is not None and _is_action(target), \
                f"ControlAction object {oid!r} does not resolve to an emitted action entity"
            assert target.get("actionStatus"), \
                f"ControlAction target {oid!r} carries no actionStatus"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="proc-minimal",
        area="profiles",
        expected_profile_uri=PROCESS_URI,
        seed_files=(SeedFile("data.csv", "a,b\n1,2\n3,4\n"),),
        append_system_prompt=STRICT_PREAMBLE,
        # NOTE: advisory mode's Stop hook does not checkpoint, so the session-end events land
        # after the agent's final `rcr checkpoint` and the post-session validation sees a
        # (benign) crate_stale warning. So accept warning here; the crate is otherwise fully
        # specified (the strengthened check below asserts every expected field).
        coverage_tags=frozenset({
            "cmd:start", "cmd:software", "cmd:input", "cmd:run", "cmd:output",
            "cmd:checkpoint", "cmd:validate",
            "flag:start:--mode", "flag:start:--profile", "flag:software:--version",
            "flag:input:--role", "flag:input:--description",
            "flag:output:--role", "flag:output:--required", "flag:run:--outputs",
            "flag:validate:--json",
            "entity:CreateAction", "entity:File", "entity:SoftwareApplication",
            "entity:Person", "entity:Dataset", "entity:Profile",
            "prop:action:result", "prop:action:instrument",
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
            "prop:action:object",
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
