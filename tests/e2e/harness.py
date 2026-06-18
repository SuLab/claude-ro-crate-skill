from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from tests.e2e.spec import ScenarioResult, ScenarioSpec

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = REPO_ROOT / ".venv" / "bin"
RCR = VENV_BIN / "rcr"
CRATE_REL = Path(".ro-crate-run") / "ro-crate" / "ro-crate-metadata.json"

Launcher = Callable[[ScenarioSpec, Path, dict], "tuple[int, str]"]


def build_env(workdir: Path) -> dict:
    """Environment that makes the skill `rcr` + hooks resolve to the editable repo src."""
    env = dict(os.environ)
    env["PATH"] = f"{VENV_BIN}:{env.get('PATH', '')}"
    env["CLAUDE_PROJECT_DIR"] = str(workdir)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def _seed(workdir: Path, spec: ScenarioSpec) -> None:
    for sf in spec.seed_files:
        target = workdir / sf.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sf.content)
        if sf.executable:
            target.chmod(0o755)
    if spec.git_init:
        subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
        subprocess.run(["git", "config", "user.email", "e2e@test.local"], cwd=workdir, check=True)
        subprocess.run(["git", "config", "user.name", "e2e"], cwd=workdir, check=True)
        if spec.git_commit and spec.seed_files:
            subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=workdir, check=True)


def claude_launcher(spec: ScenarioSpec, workdir: Path, env: dict) -> tuple[int, str]:
    """Launch a real headless claude session for the scenario."""
    cmd = [
        "claude", "-p", spec.prompt,
        "--model", spec.model,
        "--permission-mode", "bypassPermissions",
        "--add-dir", str(workdir),
    ]
    if spec.append_system_prompt:
        cmd += ["--append-system-prompt", spec.append_system_prompt]
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, env=env, capture_output=True, text=True,
            timeout=spec.timeout, stdin=subprocess.DEVNULL,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return 124, f"TIMEOUT after {spec.timeout}s\n{out}{err}"


def rcr_json(args: list, workdir: Path, env: dict) -> Optional[dict]:
    proc = subprocess.run(
        [str(RCR), *args], cwd=workdir, env=env, capture_output=True, text=True,
    )
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def run_scenario(
    spec: ScenarioSpec,
    *,
    model: Optional[str] = None,
    launcher: Optional[Launcher] = None,
) -> ScenarioResult:
    """Run one scenario and return its result.

    The temp workdir is left on disk so the caller can run file-based assertions
    (e.g. the public-export leak scan). The caller owns cleanup — see
    `tests/e2e/run.py` and `test_e2e_scenarios.py` which remove it after asserting.
    """
    if model:
        spec = ScenarioSpec(**{**spec.__dict__, "model": model})
    launcher = launcher or claude_launcher
    workdir = Path(tempfile.mkdtemp(prefix=f"rcr-e2e-{spec.name}-"))
    _seed(workdir, spec)
    env = build_env(workdir)
    exit_code, transcript = launcher(spec, workdir, env)

    crate_path = workdir / CRATE_REL
    graph = None
    if crate_path.exists():
        try:
            graph = json.loads(crate_path.read_text())["@graph"]
        except (json.JSONDecodeError, KeyError):
            graph = None

    validate_json = rcr_json(["validate", "--json"], workdir, env)
    status_json = rcr_json(["status", "--json"], workdir, env)

    return ScenarioResult(
        spec=spec, workdir=workdir,
        crate_path=crate_path if crate_path.exists() else None,
        graph=graph, transcript=transcript,
        validate_json=validate_json, status_json=status_json,
        claude_exit=exit_code,
    )
