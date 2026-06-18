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
