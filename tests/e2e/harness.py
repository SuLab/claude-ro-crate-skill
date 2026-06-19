from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Optional

from tests.e2e.spec import ScenarioResult, ScenarioSpec

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = REPO_ROOT / ".venv" / "bin"
RCR = VENV_BIN / "rcr"
SRC_PKG = REPO_ROOT / "src" / "ro_crate_run"
CRATE_REL = Path(".ro-crate-run") / "ro-crate" / "ro-crate-metadata.json"

Launcher = Callable[[ScenarioSpec, Path, dict], "tuple[int, str]"]

# Source-of-truth paths an e2e agent must never modify. The skill's `rcr` resolves
# `ro_crate_run` to the editable repo `src/`, so a headless agent running under
# bypassPermissions could otherwise "fix" the very code under test and invalidate
# results. `protect_repo()` makes these read-only while sessions run (execution only
# reads them; the materializer writes into each temp project, never the repo).
_PROTECT_PATHS = ["src", "skills", "hooks", "templates", "SPEC.md", "CLAUDE.md"]


def _set_tree_writable(path: Path, *, writable: bool) -> None:
    if not path.exists():
        return
    items = [path, *path.rglob("*")] if path.is_dir() else [path]
    for p in items:
        try:
            mode = p.stat().st_mode
            p.chmod(mode | 0o200 if writable else mode & ~0o222)
        except OSError:
            pass


@contextlib.contextmanager
def protect_repo() -> Iterator[None]:
    """Make the repo's source-of-truth read-only for the duration of e2e sessions."""
    for rel in _PROTECT_PATHS:
        _set_tree_writable(REPO_ROOT / rel, writable=False)
    try:
        yield
    finally:
        for rel in _PROTECT_PATHS:
            _set_tree_writable(REPO_ROOT / rel, writable=True)


def repo_source_dirty() -> str:
    """Return `git status --porcelain` for protected paths (empty == clean)."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", *_PROTECT_PATHS],
        capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _IGNORE(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))}


def _hash_tree(root: Path) -> str:
    """Stable hash of a source tree's contents.

    Includes ANY file present — notably .pyc / __pycache__ — so a bypassPermissions agent
    cannot evade tamper detection by poisoning a bytecode cache (which Python would import
    in preference to the .py). Legitimate bytecode writes are suppressed by
    PYTHONDONTWRITEBYTECODE=1 in `build_env`, so the snapshot has no .pyc at baseline and
    any post-run .pyc is necessarily a plant.
    """
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        h.update(str(p.relative_to(root)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def snapshot_source() -> tuple[Path, str]:
    """Copy the `ro_crate_run` package into a throwaway dir and return (parent, hash).

    The scenario env points PYTHONPATH here, so the agent's `rcr`, the skill scripts,
    and the plugin hooks all import THIS copy (the editable `.pth` and `_bootstrap`'s
    bare-import probe both yield to PYTHONPATH). A bypassPermissions agent therefore
    cannot make its own crate pass by editing the repo's `src/` — that source is never
    imported. If the agent instead edits the snapshot it ran against, the post-run hash
    won't match this baseline and the scenario is failed (see `run_scenario`).
    """
    snap = Path(tempfile.mkdtemp(prefix="rcr-e2e-src-"))
    shutil.copytree(SRC_PKG, snap / "ro_crate_run", ignore=_IGNORE)
    return snap, _hash_tree(snap / "ro_crate_run")


def build_env(workdir: Path, snapshot: Optional[Path] = None) -> dict:
    """Environment that makes the skill `rcr` + hooks resolve to an isolated src snapshot."""
    env = dict(os.environ)
    env["PATH"] = f"{VENV_BIN}:{env.get('PATH', '')}"
    env["CLAUDE_PROJECT_DIR"] = str(workdir)
    if snapshot is not None:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{snapshot}{os.pathsep}{existing}" if existing else str(snapshot)
        # No bytecode caches in the snapshot, so a planted .pyc can't shadow a .py to evade
        # the snapshot-integrity hash (which now includes .pyc). See _hash_tree.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
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
        # A remote URL so git provenance (#git/state remote) is exercised.
        subprocess.run(
            ["git", "remote", "add", "origin", "https://example.invalid/e2e-repo.git"],
            cwd=workdir, check=True,
        )
        if spec.git_commit and spec.seed_files:
            subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=workdir, check=True)


def claude_launcher(spec: ScenarioSpec, workdir: Path, env: dict) -> tuple[int, str]:
    """Launch a real headless claude session for the scenario.

    Resilient to a momentarily-missing `claude` binary: the Claude Code CLI auto-updates
    itself by swapping its symlink, leaving brief windows where `claude` is not on PATH.
    Without retry a whole concurrent run would fail with FileNotFoundError mid-flight (an
    environmental flap, not a scenario failure). Resolve the binary per attempt and retry.
    """
    tail = [
        "-p", spec.prompt,
        "--model", spec.model,
        "--permission-mode", "bypassPermissions",
        "--add-dir", str(workdir),
    ]
    if spec.append_system_prompt:
        tail += ["--append-system-prompt", spec.append_system_prompt]
    last_err: Optional[Exception] = None
    for _attempt in range(6):
        claude_bin = shutil.which("claude", path=env.get("PATH")) or "claude"
        try:
            proc = subprocess.run(
                [claude_bin, *tail], cwd=workdir, env=env, capture_output=True, text=True,
                timeout=spec.timeout, stdin=subprocess.DEVNULL,
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except FileNotFoundError as exc:
            last_err = exc
            time.sleep(2.0)  # binary briefly gone (auto-update symlink swap); resolve + retry
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            err = exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            return 124, f"TIMEOUT after {spec.timeout}s\n{out}{err}"
    return 127, f"claude binary unavailable after retries (environmental): {last_err}"


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
    snapshot, baseline_hash = snapshot_source()
    try:
        _seed(workdir, spec)
        env = build_env(workdir, snapshot=snapshot)
        if spec.env:
            env.update(spec.env)
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
        # The snapshot is the code that actually ran; if it changed, the agent edited
        # the code under test and this scenario's crate is untrustworthy.
        tampered = _hash_tree(snapshot / "ro_crate_run") != baseline_hash
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)

    return ScenarioResult(
        spec=spec, workdir=workdir,
        crate_path=crate_path if crate_path.exists() else None,
        graph=graph, transcript=transcript,
        validate_json=validate_json, status_json=status_json,
        claude_exit=exit_code, source_tampered=tampered,
    )
