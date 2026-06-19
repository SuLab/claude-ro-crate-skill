from __future__ import annotations

import json
from pathlib import Path

from ro_crate_run import commands


def test_install_project_vendors_package(tmp_path: Path) -> None:
    assert commands.install_project(str(tmp_path)) == 0
    vendored = tmp_path / ".claude" / "lib" / "ro_crate_run" / "__init__.py"
    assert vendored.exists(), "package must be vendored under .claude/lib"
    # Skill + hooks still installed.
    assert (tmp_path / ".claude" / "skills" / "ro-crate-run" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "hooks" / "_bootstrap.py").exists()
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "FileChanged" in settings["hooks"]


def test_install_project_vendors_validation_contexts(tmp_path: Path) -> None:
    # L2 JSON-LD expansion loads the vendored RO-Crate / workflow-run contexts via
    # resources.files("ro_crate_run") / "assets" / "contexts"; the vendored package MUST
    # carry them (and the assets package init) or a vendored deployment cannot validate L2.
    assert commands.install_project(str(tmp_path)) == 0
    assets = tmp_path / ".claude" / "lib" / "ro_crate_run" / "assets"
    assert (assets / "__init__.py").exists(), "assets subpackage not vendored (unimportable)"
    contexts = assets / "contexts"
    for name in ("ro-crate-1.2.jsonld", "workflow-run.jsonld"):
        ctx = contexts / name
        assert ctx.exists() and ctx.read_text(encoding="utf-8"), f"context {name} not vendored"


def test_install_project_installs_both_skills(tmp_path: Path) -> None:
    assert commands.install_project(str(tmp_path)) == 0
    skills = tmp_path / ".claude" / "skills"
    assert (skills / "ro-crate-run" / "SKILL.md").exists()
    assert (skills / "ro-crate-run-admin" / "SKILL.md").exists(), "admin skill not installed"
