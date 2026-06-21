"""Host- and filesystem-inspection helpers behind ``rcr software`` / ``rcr input``:
probe an executable's version, scan the project for dependency/workflow manifests,
and classify a declared path's existence."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import adapters
from .constants import CONTAINER_MANIFESTS, DEPENDENCY_MANIFESTS
from .context import ProjectContext
from .fs import sha256_file
from .journal import EventWriter
from .proc import run_capture

# Workflow-definition suffixes scanned by glob. ``.cwl`` is recognized by the
# adapter registry (its ``kind`` tag derives from the engine name); ``.wdl`` is a
# documented orphan with no adapter, so it is scanned explicitly here.
_GLOB_WORKFLOW_SUFFIXES: tuple[str, ...] = (".cwl", ".wdl")


def classify_existence(path: str, kind: str, required: bool) -> str:
    """Classify a declared input/output path's existence from its shape on disk."""
    if "://" in path:
        return "observed remote"
    if Path(path).exists():
        return "observed local"
    if kind == "output":
        return "expected" if required else "declared-only"
    return "missing" if required else "declared-only"


def scan_lockfiles(ctx: ProjectContext) -> None:
    """Emit dependency.lockfile.observed events for project manifests and workflow defs.

    Discovers exact-name dependency/container manifests (lockfiles, Dockerfile/
    Containerfile) plus CWL/WDL workflow-definition files, recording each with its
    sha256 file record.
    """
    writer = EventWriter(ctx.state_dir)
    # Dependency/environment manifests matched by exact filename (lockfiles, package
    # manifests, workflow definitions, container files); Dockerfile/Containerfile are
    # recorded as kind="container", the rest as kind="lockfile".
    for name in (*DEPENDENCY_MANIFESTS, "Dockerfile", "Containerfile"):
        candidate = ctx.project_dir / name
        if candidate.exists() and candidate.is_file():
            kind = "container" if name in CONTAINER_MANIFESTS else "lockfile"
            writer.append(
                "dependency.lockfile.observed",
                {
                    "path": name,
                    "kind": kind,
                    "file_record": sha256_file(candidate),
                },
                source_kind="human_cli",
            )
    # CWL/WDL workflow definition files. The kind tag for adapter-recognized engines
    # derives from the registry; the orphan .wdl falls back to a suffix-derived tag.
    for suffix in _GLOB_WORKFLOW_SUFFIXES:
        for candidate in ctx.project_dir.glob(f"*{suffix}"):
            if not candidate.is_file():
                continue
            engine = adapters.engine_for_path(candidate)
            wf_kind = f"{engine}-workflow" if engine else f"{suffix.lstrip('.')}-workflow"
            writer.append(
                "dependency.lockfile.observed",
                {
                    "path": str(candidate.relative_to(ctx.project_dir)),
                    "kind": wf_kind,
                    "file_record": sha256_file(candidate),
                },
                source_kind="human_cli",
            )


def probe_software(command_or_name: str) -> tuple[str | None, str | None]:
    """Resolve an executable on PATH and read its first ``--version`` line, if any.

    Returns ``(version, executable_path)``; either element is ``None`` when the
    executable is absent or reports no version output.
    """
    executable = shutil.which(command_or_name)
    version = None
    if executable:
        # run_capture returns None on nonzero exit / OSError / TimeoutExpired, so a hung
        # or failing `--version` degrades to "no version" instead of raising.
        proc = run_capture([executable, "--version"], timeout=5)
        if proc is not None:
            output = (proc.stdout or proc.stderr).strip()
            if output:
                version = output.splitlines()[0]
    return version, executable
