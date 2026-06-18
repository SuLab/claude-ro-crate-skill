import json
import subprocess
import sys
from pathlib import Path


def test_plugin_manifest_namespace(repo_root: Path) -> None:
    manifest = repo_root / ".claude-plugin" / "plugin.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["name"] == "ro-crate-run"
    assert data["skills"] == "./skills"
    # The standard hooks/hooks.json is auto-loaded from the plugin root; declaring it
    # in the manifest too makes Claude Code reject the plugin ("Duplicate hooks file").
    # Guard against re-introducing that load failure.
    assert "hooks" not in data
    assert (repo_root / "hooks" / "hooks.json").exists()


def test_skill_and_wrappers_exist(repo_root: Path) -> None:
    assert (repo_root / "skills/ro-crate-run/SKILL.md").exists()
    assert (repo_root / "skills/ro-crate-run/scripts/rcr").exists()
    assert (repo_root / "bin/rcr").exists()
    assert (repo_root / "hooks/hooks.json").exists()


def test_skill_script_rcr_invokes_cli_help(repo_root: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(repo_root / "skills/ro-crate-run/scripts/rcr"), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "checkpoint" in result.stdout
