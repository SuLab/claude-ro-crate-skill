"""Offline unit tests for the e2e harness/assertions, using a fake launcher (no claude)."""
from __future__ import annotations

import shutil
import subprocess

from tests.e2e import assertions as A
from tests.e2e.harness import REPO_ROOT, run_scenario
from tests.e2e.spec import ScenarioSpec, SeedFile

PROCESS_URI = "https://w3id.org/ro/wfrun/process/0.5"


def _fake_min_launcher(spec, workdir, env):
    """Mimic what claude would do for proc-minimal by running rcr directly."""
    rcr = str(REPO_ROOT / ".venv" / "bin" / "rcr")
    cmds = [
        [rcr, "start", "Fake minimal", "--mode", "advisory", "--profile", "process"],
        [rcr, "software", "python3", "--version", "Python 3.12.3"],
        [rcr, "output", "out.txt", "--role", "result", "--required"],
        [rcr, "run", "--outputs", "out.txt", "--",
         "python3", "-c", "open('out.txt','w').write('ok\\n')"],
        [rcr, "checkpoint"],
    ]
    log = []
    for c in cmds:
        p = subprocess.run(c, cwd=workdir, env=env, capture_output=True, text=True)
        log.append(f"$ {' '.join(c)}\n{p.stdout}{p.stderr}")
    return 0, "\n".join(log)


def test_scenario_spec_defaults() -> None:
    spec = ScenarioSpec(name="x", area="profiles", prompt="do it")
    assert spec.model == "sonnet"
    assert spec.git_init is True
    assert spec.expect_validation_status == ("passed", "warning")
    assert spec.coverage_tags == frozenset()
    sf = SeedFile(path="a.txt", content="hi")
    assert sf.executable is False


def test_run_scenario_with_fake_launcher() -> None:
    spec = ScenarioSpec(
        name="fake-min", area="profiles", prompt="(fake)",
        expected_profile_uri=PROCESS_URI,
    )
    result = run_scenario(spec, launcher=_fake_min_launcher)
    try:
        assert result.claude_exit == 0
        assert result.crate_path is not None and result.crate_path.exists()
        assert result.graph is not None
        assert result.validate_json is not None
        assert result.validate_json["errors"] == []
        assert result.validate_json["profile"] == "process"
    finally:
        shutil.rmtree(result.workdir, ignore_errors=True)


def test_assertions_on_fake_crate() -> None:
    spec = ScenarioSpec(
        name="fake-assert", area="profiles", prompt="(fake)",
        expected_profile_uri=PROCESS_URI,
        coverage_tags=frozenset({"cmd:start", "cmd:run", "cmd:output", "entity:CreateAction"}),
    )
    result = run_scenario(spec, launcher=_fake_min_launcher)
    try:
        A.assert_crate(result)
        A.assert_entity_type(result.graph, "CreateAction", min_count=1)
        A.assert_profile(result.graph, PROCESS_URI)
    finally:
        shutil.rmtree(result.workdir, ignore_errors=True)


def test_descriptor_assertion_catches_missing_root() -> None:
    bad_graph = [{"@id": "ro-crate-metadata.json",
                  "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"}}]
    try:
        A.assert_descriptor(bad_graph)
    except AssertionError as exc:
        assert "root" in str(exc)
    else:
        raise AssertionError("expected assert_descriptor to fail on missing root")
