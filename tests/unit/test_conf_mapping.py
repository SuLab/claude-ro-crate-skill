"""Conformance unit tests for materialize/mapping.py (Agent B slice).

Covers the RO-Crate 1.2 / Run-Crate 0.5 conformance fixes implemented in mapping.py:
H3 (HowToStep.workExample on every step), H4 (ComputationalWorkflow.hasPart -> tools),
M5 (engine url + softwareVersion), M6 (OrganizeAction -> Action for subagents/phases),
M7 (ContainerImage.additionalType), L2 (FormalParameter.conformsTo), L4 (raw-command
object), L5 (environment on command CreateAction), L8-aux (contentSize on aux Files).
"""
from __future__ import annotations

from pathlib import Path

from ro_crate_run.ids import IdMap, software_entity_id
from ro_crate_run.materialize import mapping
from ro_crate_run.models import CommandRecord, RunModel

_FP_PROFILE = "https://bioschemas.org/profiles/FormalParameter/1.0-RELEASE"
_DOCKER = "https://w3id.org/ro/terms/workflow-run#DockerImage"
_SIF = "https://w3id.org/ro/terms/workflow-run#SIFImage"


def _model(**kw: object) -> RunModel:
    base: dict[str, object] = dict(
        run_id="run_x",
        title="T",
        description="d",
        created_at="2026-06-17T00:00:00.000000Z",
        updated_at="2026-06-17T01:00:00.000000Z",
        selected_profile="provenance",
        requested_profile="auto",
        profile_uri="https://w3id.org/ro/wfrun/provenance/0.5",
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
# H3 — HowToStep.workExample on EVERY step (resolving ref)
# ---------------------------------------------------------------------------


def test_h3_step_with_command_uses_tool_workexample(tmp_path: Path) -> None:
    model = _model(
        steps={"s1": {"status": "completed"}},
        commands=[_cmd(step_id="s1", argv=["bwa", "mem"])],
        workflow={"path": "Snakefile", "engine": "snakemake"},
    )
    ents = mapping.build_steps(model, IdMap(tmp_path))
    step = next(e for e in ents if e.get("@type") == "HowToStep")
    assert step["workExample"] == {"@id": software_entity_id("bwa")}


def test_h3_commandless_step_falls_back_to_engine(tmp_path: Path) -> None:
    model = _model(
        steps={"all": {"status": "completed"}},
        commands=[],
        workflow={"path": "Snakefile", "engine": "snakemake"},
    )
    ents = mapping.build_steps(model, IdMap(tmp_path))
    step = next(e for e in ents if e.get("@type") == "HowToStep")
    assert step["workExample"] == {"@id": "#actor/engine/snakemake"}
    # The engine ref MUST resolve to an entity build_actors emits.
    actor_ids = {a["@id"] for a in mapping.build_actors(model)}
    assert "#actor/engine/snakemake" in actor_ids


def test_h3_commandless_step_unknown_engine_falls_back_to_workflow(tmp_path: Path) -> None:
    model = _model(
        steps={"all": {"status": "completed"}},
        commands=[],
        workflow={"path": "pipeline.wf", "engine": "unknown"},
    )
    ents = mapping.build_steps(model, IdMap(tmp_path))
    step = next(e for e in ents if e.get("@type") == "HowToStep")
    # No known engine -> the workflow entity itself (always present when steps exist).
    assert step["workExample"] == {"@id": "pipeline.wf"}


def test_h3_every_step_has_workexample(tmp_path: Path) -> None:
    model = _model(
        steps={"a": {"status": "completed"}, "b": {"status": "completed"}},
        commands=[_cmd(step_id="a", argv=["samtools", "sort"])],
        workflow={"path": "Snakefile", "engine": "snakemake"},
    )
    ents = mapping.build_steps(model, IdMap(tmp_path))
    steps = [e for e in ents if e.get("@type") == "HowToStep"]
    assert len(steps) == 2
    assert all("workExample" in s for s in steps)


# ---------------------------------------------------------------------------
# H4 — ComputationalWorkflow.hasPart -> orchestrated tools (resolving)
# ---------------------------------------------------------------------------


def test_h4_workflow_haspart_lists_resolving_tools(tmp_path: Path) -> None:
    model = _model(
        workflow={"path": "Snakefile", "engine": "snakemake"},
        steps={"s1": {"status": "completed"}},
        commands=[_cmd(step_id="s1", argv=["bwa", "mem"])],
        software=[{"name": "samtools", "version": "1.19"}],
    )
    idmap = IdMap(tmp_path)
    wf = mapping.build_workflow(model, idmap)[0]
    haspart = {r["@id"] for r in wf["hasPart"]}
    assert software_entity_id("bwa") in haspart
    assert software_entity_id("samtools") in haspart
    assert "#actor/engine/snakemake" in haspart
    # Every hasPart ref MUST resolve against build_software + build_actors emitted ids.
    emitted = {e["@id"] for e in mapping.build_software(model)}
    emitted |= {a["@id"] for a in mapping.build_actors(model)}
    for ref in haspart:
        assert ref in emitted, ref


def test_h4_no_tools_omits_haspart(tmp_path: Path) -> None:
    # Synthetic workflow with no commands/software but a known engine still lists the engine;
    # a workflow with truly nothing orchestrated omits hasPart rather than emitting empty.
    model = _model(
        workflow={"path": "wf.cwl", "engine": "unknown"},
        steps={"s1": {"status": "completed"}},
        commands=[],
        software=[],
    )
    wf = mapping.build_workflow(model, IdMap(tmp_path))[0]
    assert "hasPart" not in wf


# ---------------------------------------------------------------------------
# M5 — engine SoftwareApplication url + softwareVersion
# ---------------------------------------------------------------------------


def test_m5_engine_entity_has_url_and_version() -> None:
    model = _model(workflow={"path": "Snakefile", "engine": "snakemake"})
    by_id = {a["@id"]: a for a in mapping.build_actors(model)}
    engine = by_id["#actor/engine/snakemake"]
    assert engine["url"] == "https://snakemake.github.io/"
    assert engine["softwareVersion"] == "unknown"


def test_m5_engine_version_uses_observed_when_present() -> None:
    model = _model(workflow={"path": "main.nf", "engine": "nextflow", "version": "23.10.0"})
    by_id = {a["@id"]: a for a in mapping.build_actors(model)}
    engine = by_id["#actor/engine/nextflow"]
    assert engine["url"] == "https://www.nextflow.io/"
    assert engine["softwareVersion"] == "23.10.0"


def test_m5_unknown_engine_homepage_omits_url() -> None:
    model = _model(workflow={"path": "x.foo", "engine": "homegrown"})
    by_id = {a["@id"]: a for a in mapping.build_actors(model)}
    engine = by_id["#actor/engine/homegrown"]
    assert "url" not in engine  # stripped because no homepage mapping
    assert engine["softwareVersion"] == "unknown"


# ---------------------------------------------------------------------------
# M6 — OrganizeAction misuse: subagent/phase actions are generic Action
# ---------------------------------------------------------------------------


def test_m6_subagent_action_is_generic_action() -> None:
    model = _model(
        subagents=[
            {"sequence": 5, "task_id": "t1", "event": "agent.task.created",
             "subagent_type": "reviewer", "timestamp": "2026-06-17T00:00:00Z",
             "description": "review"},
        ]
    )
    ents = mapping.build_subagent_actions(model)
    assert ents and all(e["@type"] == "Action" for e in ents)
    assert all(e["@type"] != "OrganizeAction" for e in ents)


def test_m6_phase_action_is_generic_action() -> None:
    model = _model(
        phases={"design": {"status": "completed", "timestamp": "2026-06-17T00:00:00Z"}}
    )
    ents = mapping.build_phase_actions(model)
    assert ents and all(e["@type"] == "Action" for e in ents)


# ---------------------------------------------------------------------------
# M7 — ContainerImage.additionalType (DockerImage / SIFImage)
# ---------------------------------------------------------------------------


def test_m7_docker_registry_gets_dockerimage_type() -> None:
    model = _model(
        containers=[{"registry": "docker.io", "image": "library/python", "tag": "3.12",
                     "digest": "sha256:abc"}]
    )
    ent = mapping.build_containers(model)[0]
    assert ent["additionalType"] == {"@id": _DOCKER}
    assert ent["registry"] == "docker.io"
    assert ent["name"] == "library/python"


def test_m7_quay_and_ghcr_get_dockerimage() -> None:
    for reg in ("quay.io", "ghcr.io", "registry.example.com", ""):
        model = _model(containers=[{"registry": reg, "image": "x/y", "tag": "1"}])
        ent = mapping.build_containers(model)[0]
        assert ent["additionalType"] == {"@id": _DOCKER}, reg


def test_m7_sif_ref_gets_sifimage() -> None:
    model = _model(containers=[{"registry": "", "image": "my-image.sif", "tag": ""}])
    ent = mapping.build_containers(model)[0]
    assert ent["additionalType"] == {"@id": _SIF}


def test_m7_singularity_keyword_gets_sifimage() -> None:
    model = _model(containers=[{"registry": "singularity-hub.org", "image": "x/y", "tag": ""}])
    ent = mapping.build_containers(model)[0]
    assert ent["additionalType"] == {"@id": _SIF}


# ---------------------------------------------------------------------------
# L2 — FormalParameter.conformsTo + Profile contextual entity
# ---------------------------------------------------------------------------


def test_l2_build_parameters_conformsto() -> None:
    model = _model(parameters=[{"name": "threads", "type": "Integer", "value": "4"}])
    ents = mapping.build_parameters(model)
    fps = [e for e in ents if e.get("@type") == "FormalParameter"]
    assert fps and all(e["conformsTo"] == {"@id": _FP_PROFILE} for e in fps)
    # The referenced Profile entity is emitted exactly once and resolves.
    profiles = [e for e in ents if e.get("@id") == _FP_PROFILE]
    assert len(profiles) == 1
    assert profiles[0]["@type"] == ["CreativeWork", "Profile"]


def test_l2_no_parameters_emits_no_profile_entity() -> None:
    assert mapping.build_parameters(_model()) == []


def test_l2_workflow_formal_parameters_conformsto() -> None:
    model = _model(
        workflow={"path": "Snakefile", "engine": "snakemake"},
        inputs=[{"path": "in.txt", "role": "primary"}],
        outputs=[{"path": "out.txt"}],
    )
    params, _ = mapping.workflow_formal_parameters(model)
    fps = [e for e in params if e.get("@type") == "FormalParameter"]
    assert fps and all(e["conformsTo"] == {"@id": _FP_PROFILE} for e in fps)
    assert sum(1 for e in params if e.get("@id") == _FP_PROFILE) == 1


# ---------------------------------------------------------------------------
# L4 — raw-command CreateAction object [{"@id": "./"}]
# ---------------------------------------------------------------------------


def test_l4_raw_command_object_is_root_dataset() -> None:
    model = _model(
        raw_commands=[{"sequence": 3, "command": "make build", "timestamp": "2026-06-17T00:00:00Z"}]
    )
    ents = mapping.build_raw_command_actions(model)
    action = next(e for e in ents if str(e.get("@id", "")).startswith("#raw-command/"))
    assert action["@type"] == "CreateAction"
    assert action["object"] == [{"@id": "./"}]


# ---------------------------------------------------------------------------
# L5 — environment refs on the command CreateAction
# ---------------------------------------------------------------------------


def test_l5_command_action_environment_refs(tmp_path: Path) -> None:
    cmd = _cmd(argv=["python3", "x.py"], outputs=["out.txt"], terminal_status="completed")
    ents = mapping.build_command_action(
        cmd, IdMap(tmp_path), tmp_path, env_ids=["#env/SEED", "#env/THREADS"]
    )
    action = ents[0]
    assert action["environment"] == [{"@id": "#env/SEED"}, {"@id": "#env/THREADS"}]


def test_l5_no_env_ids_omits_environment(tmp_path: Path) -> None:
    cmd = _cmd(terminal_status="completed", outputs=["out.txt"])
    action = mapping.build_command_action(cmd, IdMap(tmp_path), tmp_path)[0]
    assert "environment" not in action


# ---------------------------------------------------------------------------
# L8-aux — contentSize on sidecar/log/git-diff/dependency File entities
# ---------------------------------------------------------------------------


def test_l8aux_sidecar_log_content_size(tmp_path: Path) -> None:
    (tmp_path / "sidecar.json").write_text('{"x": 1}', encoding="utf-8")
    (tmp_path / "stdout.txt").write_text("hello\n", encoding="utf-8")
    cmd = _cmd(
        terminal_status="completed",
        outputs=["out.txt"],
        sidecar="sidecar.json",
        stdout_log="stdout.txt",
    )
    ents = mapping.build_command_action(cmd, IdMap(tmp_path), tmp_path)
    by_id = {e["@id"]: e for e in ents}
    assert by_id["sidecar.json"]["contentSize"] == str(len('{"x": 1}'))
    assert by_id["stdout.txt"]["contentSize"] == str(len("hello\n"))


def test_l8aux_missing_sidecar_file_omits_content_size(tmp_path: Path) -> None:
    cmd = _cmd(terminal_status="completed", outputs=["out.txt"], sidecar="absent.json")
    ents = mapping.build_command_action(cmd, IdMap(tmp_path), tmp_path)
    sidecar = next(e for e in ents if e["@id"] == "absent.json")
    assert "contentSize" not in sidecar


def test_l8aux_git_diff_content_size(tmp_path: Path) -> None:
    (tmp_path / "diff.patch").write_text("diff --git a b\n", encoding="utf-8")
    model = _model(git={"available": True, "branch": "main", "diff_file": "diff.patch"})
    ents = mapping.build_git(model, tmp_path)
    diff = next(e for e in ents if e["@id"] == "diff.patch")
    assert diff["contentSize"] == str(len("diff --git a b\n"))


def test_l8aux_git_no_project_dir_omits_content_size() -> None:
    model = _model(git={"available": True, "diff_file": "diff.patch"})
    ents = mapping.build_git(model)
    diff = next(e for e in ents if e["@id"] == "diff.patch")
    assert "contentSize" not in diff


def test_l8aux_dependency_content_size(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("rocrate==0.15\n", encoding="utf-8")
    model = _model(
        dependencies=[{"path": "requirements.txt", "kind": "pip", "file_record": "sha256:deadbeef"}]
    )
    ents = mapping.build_dependencies(model, tmp_path)
    dep = ents[0]
    assert dep["contentSize"] == str(len("rocrate==0.15\n"))
    assert dep["identifier"]["value"] == "deadbeef"


def test_l8aux_dependency_no_project_dir_omits_content_size() -> None:
    model = _model(dependencies=[{"path": "requirements.txt", "kind": "pip"}])
    ents = mapping.build_dependencies(model)
    assert "contentSize" not in ents[0]
