"""Unit tests for materialize/mapping.py entity builders."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ro_crate_run.ids import IdMap, software_entity_id
from ro_crate_run.materialize import mapping
from ro_crate_run.models import CommandRecord, RunModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(**kw: object) -> RunModel:
    base: dict[str, object] = dict(
        run_id="run_x",
        title="T",
        description="d",
        created_at="2026-06-17T00:00:00.000000Z",
        updated_at="2026-06-17T01:00:00.000000Z",
        selected_profile="process",
        requested_profile="auto",
        profile_uri="https://w3id.org/ro/wfrun/process/0.5",
        mode="monitored",
    )
    base.update(kw)
    return RunModel(**base)  # type: ignore[arg-type]


def _cmd(**kw: object) -> CommandRecord:
    base: dict[str, object] = dict(
        command_id="cmd_000001",
        event_id="evt_1",
        action_id="urn:uuid:1111",
        argv=["python3", "run.py"],
        display_command="python3 run.py",
        cwd="/proj",
        started_at="2026-06-17T00:00:00.000000Z",
    )
    base.update(kw)
    return CommandRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Task 2: build_actors
# ---------------------------------------------------------------------------


def test_build_actors_emits_core_actors() -> None:
    model = _model(
        environment={"python": "3.12.1", "rocrate_package_version": "0.15.0", "os": "Linux"}
    )
    actors = mapping.build_actors(model)
    by_id = {a["@id"]: a for a in actors}
    assert by_id["#actor/human"]["@type"] == "Person"
    assert by_id["#actor/rcr"]["@type"] == "SoftwareApplication"
    assert by_id["#actor/claude-code"]["@type"] == "SoftwareApplication"
    assert by_id["#actor/python"]["softwareVersion"] == "3.12.1"
    assert by_id["#actor/ro-crate-py"]["softwareVersion"] == "0.15.0"


def test_build_actors_conditional_engine_and_model() -> None:
    model = _model(
        environment={
            "python": "3.12.1",
            "rocrate_package_version": "0.15.0",
            "os": "L",
            "claude_model": "claude-opus-4-8",
            "shell": "/bin/zsh",
        },
        workflow={"path": "Snakefile", "engine": "snakemake"},
    )
    by_id = {a["@id"]: a for a in mapping.build_actors(model)}
    assert by_id["#actor/claude-model"]["@type"] == "SoftwareApplication"
    assert by_id["#actor/shell"]["@type"] == "SoftwareApplication"
    assert by_id["#actor/engine/snakemake"]["name"] == "snakemake"


def test_build_actors_omits_absent_optionals() -> None:
    by_id = {
        a["@id"]: a
        for a in mapping.build_actors(
            _model(
                environment={"python": "3.12.1", "rocrate_package_version": "0.15.0", "os": "L"}
            )
        )
    }
    assert "#actor/claude-model" not in by_id
    assert "#actor/shell" not in by_id
    assert not any(k.startswith("#actor/engine/") for k in by_id)


# ---------------------------------------------------------------------------
# Task 3: command_action_type, build_software, build_command_action
# ---------------------------------------------------------------------------


def test_command_action_type_matrix() -> None:
    assert mapping.command_action_type(_cmd(outputs=["out.txt"])) == "CreateAction"
    assert mapping.command_action_type(_cmd(inputs=["a.txt"], outputs=["a.txt"])) == "UpdateAction"
    assert mapping.command_action_type(_cmd()) == "Action"
    assert (
        mapping.command_action_type(
            _cmd(argv=["rm", "old.txt"], display_command="rm old.txt")
        )
        == "DeleteAction"
    )


def test_build_software_covers_instruments(tmp_path: Path) -> None:
    model = _model()
    model.software = [{"name": "cwltool", "command": "cwltool", "version": "3.1"}]
    model.commands = [_cmd(argv=["python3", "run.py"], terminal_status="completed")]
    ids = {s["@id"] for s in mapping.build_software(model)}
    assert software_entity_id("cwltool") in ids
    assert software_entity_id("python3") in ids


def test_build_command_action_resolves_instrument(tmp_path: Path) -> None:
    idmap = IdMap(tmp_path)
    cmd = _cmd(
        outputs=["results/out.txt"],
        terminal_status="completed",
        exit_code=0,
        ended_at="2026-06-17T00:01:00.000000Z",
        stdout_log=".ro-crate-run/logs/cmd_000001.stdout.txt",
        sidecar=".ro-crate-run/commands/cmd_000001.json",
    )
    entities = mapping.build_command_action(cmd, idmap, Path("/proj"))
    action = entities[0]
    assert action["@type"] == "CreateAction"
    assert action["instrument"] == {"@id": software_entity_id("python3")}
    assert action["agent"] == {"@id": "#actor/human"}
    # log + sidecar File entities point back to the action via schema.org about
    files = entities[1:]
    assert all(f["about"] == {"@id": action["@id"]} for f in files)
    assert {f["@id"] for f in files} == {cmd.stdout_log, cmd.sidecar}


def test_build_command_action_failure_has_error() -> None:
    cmd = _cmd(
        outputs=["o"],
        terminal_status="failed",
        exit_code=2,
        ended_at="2026-06-17T00:01:00.000000Z",
    )
    action = mapping.build_command_action(
        cmd, IdMap(Path("/tmp/x_idmap_nonexistent")), Path("/proj")
    )[0]
    assert action["actionStatus"] == {"@id": "http://schema.org/FailedActionStatus"}
    assert "exited with code 2" in action["error"]


# ---------------------------------------------------------------------------
# Task 4: build_file_entity
# ---------------------------------------------------------------------------


@dataclass
class _Plan:
    file_id: str
    abs_path: Path
    declared: dict  # type: ignore[type-arg]
    copy: bool = False
    included: bool = True
    reason: str = ""


def test_build_file_entity_hashes_and_links(tmp_path: Path) -> None:
    f = tmp_path / "out.txt"
    f.write_text("hello\n")
    plan = _Plan(file_id="results/out.txt", abs_path=f, declared={"description": "Result"})
    entity = mapping.build_file_entity(plan, max_hash_bytes=1024, formal_parameter_id="#param/out")
    assert entity["@type"] == "File"
    assert entity["name"] == "out.txt"
    assert entity["identifier"]["propertyID"] == "sha256"
    assert entity["exampleOfWork"] == {"@id": "#param/out"}


def test_build_file_entity_no_formal_param_omits_example(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    plan = _Plan(file_id="x.txt", abs_path=f, declared={})
    entity = mapping.build_file_entity(plan, max_hash_bytes=1024)
    assert "exampleOfWork" not in entity


# ---------------------------------------------------------------------------
# Task 5: build_parameters, workflow_formal_parameters
# ---------------------------------------------------------------------------


def test_build_parameters_makes_formal_and_value() -> None:
    model = _model()
    model.parameters = [{"name": "threshold", "value": "0.5", "type": "Float"}]
    ents = {e["@id"]: e for e in mapping.build_parameters(model)}
    assert ents["#param/threshold"]["@type"] == "FormalParameter"
    assert ents["#param-value/threshold"]["@type"] == "PropertyValue"
    assert ents["#param-value/threshold"]["exampleOfWork"] == {"@id": "#param/threshold"}


def test_workflow_formal_parameters_only_for_workflow_profile() -> None:
    proc = _model(selected_profile="process")
    proc.inputs = [{"path": "data/in.csv"}]
    assert mapping.workflow_formal_parameters(proc) == ([], {})

    wf = _model(
        selected_profile="workflow",
        workflow={"path": "Snakefile", "engine": "snakemake"},
    )
    wf.inputs = [{"path": "data/in.csv"}, {"path": "Snakefile", "role": "workflow-definition"}]
    wf.outputs = [{"path": "results/out.txt"}]
    params, path_map = mapping.workflow_formal_parameters(wf)
    ids = {p["@id"] for p in params}
    # workflow definition is excluded; one input + one output param
    assert path_map["data/in.csv"] in ids
    assert path_map["results/out.txt"] in ids
    assert "Snakefile" not in path_map


# ---------------------------------------------------------------------------
# Task 6: build_workflow
# ---------------------------------------------------------------------------


def test_build_workflow_basic() -> None:
    wf = _model(
        selected_profile="workflow",
        workflow={"path": "Snakefile", "name": "Snakefile", "engine": "snakemake"},
    )
    ents = mapping.build_workflow(wf, IdMap(Path("/tmp/wf_idmap_none")))
    entity = ents[0]
    assert entity["@id"] == "Snakefile"
    assert set(entity["@type"]) == {"File", "SoftwareSourceCode", "ComputationalWorkflow"}
    assert entity["programmingLanguage"] == "snakemake"
    assert "HowTo" not in entity["@type"]


def test_build_workflow_with_steps_adds_howto_and_step_refs(tmp_path: Path) -> None:
    wf = _model(
        selected_profile="provenance",
        workflow={"path": "wf.cwl", "name": "wf.cwl", "engine": "cwl"},
    )
    wf.steps = {"normalize": {"status": "completed"}, "score": {"status": "completed"}}
    idmap = IdMap(tmp_path)
    entity = mapping.build_workflow(wf, idmap)[0]
    assert "HowTo" in entity["@type"]
    assert entity["step"] == [{"@id": "#step/normalize"}, {"@id": "#step/score"}]


def test_build_workflow_absent() -> None:
    assert mapping.build_workflow(_model(), IdMap(Path("/tmp/none_idmap"))) == []


# ---------------------------------------------------------------------------
# Task 7: build_steps
# ---------------------------------------------------------------------------


def test_build_steps_emits_howtostep_for_every_step(tmp_path: Path) -> None:
    model = _model(selected_profile="provenance")
    model.steps = {"normalize": {"status": "completed"}, "orphan": {"status": "started"}}
    model.commands = [
        _cmd(
            command_id="cmd_1",
            action_id="urn:uuid:a",
            step_id="normalize",
            argv=["python3", "n.py"],
        )
    ]
    idmap = IdMap(tmp_path)
    ents = {e["@id"]: e for e in mapping.build_steps(model, idmap)}
    # both steps get a HowToStep, even the orphan with no command
    assert ents["#step/normalize"]["@type"] == "HowToStep"
    assert ents["#step/orphan"]["@type"] == "HowToStep"
    # the mapped step has a workExample and a ControlAction
    assert ents["#step/normalize"]["workExample"] == {"@id": software_entity_id("python3")}
    controls = [e for e in ents.values() if e.get("@type") == "ControlAction"]
    assert controls[0]["instrument"] == {"@id": "#step/normalize"}
    assert controls[0]["object"] == {"@id": "urn:uuid:a"}


def test_build_steps_dangling_free(tmp_path: Path) -> None:
    from tests.graph_helpers import assert_no_dangling_refs

    model = _model(
        selected_profile="provenance",
        environment={"python": "3.12.1", "rocrate_package_version": "0.15.0", "os": "L"},
    )
    model.steps = {"s1": {"status": "completed"}}
    model.commands = [_cmd(command_id="c", action_id="urn:uuid:z", step_id="s1", argv=["bash", "s.sh"])]
    idmap = IdMap(tmp_path)
    graph = (
        mapping.build_actors(model)
        + mapping.build_steps(model, idmap)
        + mapping.build_software(model)
        + mapping.build_command_action(model.commands[0], idmap, Path("/proj"))
    )
    assert_no_dangling_refs(graph)


# ---------------------------------------------------------------------------
# Task 8: build_git
# ---------------------------------------------------------------------------


def test_build_git_maps_commit_branch_dirty() -> None:
    model = _model()
    model.git = {
        "available": True,
        "commit": "abc123",
        "branch": "main",
        "status": "M file.py",
        "remote": "git@x:y.git",
    }
    ents = {e["@id"]: e for e in mapping.build_git(model)}
    state = ents["#git/state"]
    assert state["identifier"] == "abc123"
    props = {p["name"]: p["value"] for p in state["additionalProperty"]}
    assert props["branch"] == "main"
    assert props["dirty"] == "true"


def test_build_git_absent_returns_empty() -> None:
    assert mapping.build_git(_model()) == []
    model_no_git = _model()
    model_no_git.git = {"available": False}
    assert mapping.build_git(model_no_git) == []


# ---------------------------------------------------------------------------
# Task 9: build_environment, build_containers, build_dependencies
# ---------------------------------------------------------------------------


def test_build_environment_property_values() -> None:
    model = _model(environment={"env_vars": {"VIRTUAL_ENV": "/x/.venv", "LANG": "C"}})
    ents = {e["@id"]: e for e in mapping.build_environment(model)}
    assert ents["#env/VIRTUAL_ENV"]["@type"] == "PropertyValue"
    assert ents["#env/VIRTUAL_ENV"]["value"] == "/x/.venv"


def test_build_containers() -> None:
    model = _model()
    model.containers = [
        {"registry": "docker.io", "image": "python", "tag": "3.12", "digest": "sha256:deadbeef"}
    ]
    ent = mapping.build_containers(model)[0]
    assert ent["@type"] == "ContainerImage"
    assert ent["registry"] == "docker.io"
    assert ent["sha256"] == "deadbeef"


def test_build_dependencies() -> None:
    model = _model()
    model.dependencies = [{"path": "requirements.txt", "kind": "pip"}]
    ent = mapping.build_dependencies(model)[0]
    assert ent["@id"] == "requirements.txt"
    assert ent["@type"] == "File"


# ---------------------------------------------------------------------------
# Task 10: build_notes_decisions, build_parameter_connections
# ---------------------------------------------------------------------------


def test_build_notes_decisions_public_only() -> None:
    model = _model()
    model.notes = [
        {"text": "pub", "visibility": "public"},
        {"text": "secret", "visibility": "private"},
    ]
    model.decisions = [{"text": "chose A", "rationale": "faster", "visibility": "public"}]
    ents = mapping.build_notes_decisions(model)
    texts = [e.get("text") for e in ents]
    assert "pub" in texts and "secret" not in texts
    decision = next(e for e in ents if e.get("text") == "chose A")
    assert "Rationale: faster" in decision["description"]


def test_build_parameter_connections_optional() -> None:
    model = _model()
    model.parameters = [
        {"name": "x", "value": "1", "connection": {"source": "#param/a", "target": "#param/b"}}
    ]
    ent = mapping.build_parameter_connections(model)[0]
    assert ent["@type"] == "ParameterConnection"
    assert ent["sourceParameter"] == {"@id": "#param/a"}
    assert ent["targetParameter"] == {"@id": "#param/b"}


