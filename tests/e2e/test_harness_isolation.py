"""Offline checks on the e2e source-isolation mechanism (no claude, always runs).

`run_scenario` copies the `ro_crate_run` package into a throwaway dir and points the
scenario's PYTHONPATH at it, so the agent's `rcr`/hooks import THAT snapshot — never the
repo `src/`. These tests use a fake launcher (plain `rcr` subprocesses, no claude) to
prove: (1) the code that runs resolves to the snapshot, (2) a clean run reports
`source_tampered=False` and builds a valid crate, (3) editing the snapshot is detected.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.e2e.harness import RCR, run_scenario
from tests.e2e.spec import ScenarioResult, ScenarioSpec

_SPEC = ScenarioSpec(
    name="iso-probe",
    area="natural",
    prompt="(offline; launcher drives rcr directly)",
    git_init=True,
    git_commit=False,
)


def _snapshot_dir(env: dict) -> Path:
    return Path(env["PYTHONPATH"].split(os.pathsep)[0])


def _rcr(workdir: Path, env: dict, *args: str) -> None:
    subprocess.run([str(RCR), *args], cwd=workdir, env=env, capture_output=True, text=True)


def test_imported_source_is_the_snapshot_not_the_repo() -> None:
    captured: dict = {}

    def launcher(spec: ScenarioSpec, workdir: Path, env: dict) -> tuple[int, str]:
        proc = subprocess.run(
            [str(RCR.parent / "python"), "-c",
             "import ro_crate_run, sys; sys.stdout.write(ro_crate_run.__file__)"],
            cwd=workdir, env=env, capture_output=True, text=True,
        )
        captured["file"] = proc.stdout.strip()
        captured["snap"] = str(_snapshot_dir(env))
        return 0, proc.stdout

    res = run_scenario(_SPEC, launcher=launcher)
    try:
        assert captured["file"].startswith(captured["snap"]), (
            f"ro_crate_run imported from {captured['file']}, not the snapshot {captured['snap']}"
        )
        assert "/src/ro_crate_run" not in captured["file"], "imported the repo src, not the snapshot"
        assert res.source_tampered is False
    finally:
        _cleanup(res)


def test_clean_run_builds_crate_and_reports_untampered() -> None:
    def launcher(spec: ScenarioSpec, workdir: Path, env: dict) -> tuple[int, str]:
        _rcr(workdir, env, "start", "Iso", "--mode", "advisory", "--profile", "auto",
             "--no-checkpoint")
        _rcr(workdir, env, "run", "--", "python3", "-c", "print('hello')")
        _rcr(workdir, env, "checkpoint")
        return 0, "ok"

    res = run_scenario(_SPEC, launcher=launcher)
    try:
        assert res.source_tampered is False
        assert res.graph is not None, "crate was not built from the snapshot code"
        assert (res.validate_json or {}).get("status") in {"passed", "warning"}
    finally:
        _cleanup(res)


def test_editing_the_snapshot_is_detected() -> None:
    def launcher(spec: ScenarioSpec, workdir: Path, env: dict) -> tuple[int, str]:
        _rcr(workdir, env, "start", "Iso", "--mode", "advisory", "--profile", "auto",
             "--no-checkpoint")
        # Simulate a rogue agent editing the very code it ran against.
        (_snapshot_dir(env) / "ro_crate_run" / "_injected.py").write_text("# tamper\n")
        _rcr(workdir, env, "checkpoint")
        return 0, "ok"

    res = run_scenario(_SPEC, launcher=launcher)
    try:
        assert res.source_tampered is True, "snapshot edit was not detected"
    finally:
        _cleanup(res)


def _cleanup(res: ScenarioResult) -> None:
    import shutil

    shutil.rmtree(res.workdir, ignore_errors=True)
