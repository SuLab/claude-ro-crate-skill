from pathlib import Path

from ro_crate_run.context import ProjectContext


def test_context_uses_project_dir_env(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ctx = ProjectContext.from_cwd(project / "subdir", env={"CLAUDE_PROJECT_DIR": str(project)})
    assert ctx.project_dir == project
    assert ctx.state_dir == project / ".ro-crate-run"


def test_context_resolves_plugin_root(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    project = tmp_path / "project"
    plugin.mkdir()
    project.mkdir()
    ctx = ProjectContext.from_cwd(project, env={"CLAUDE_PLUGIN_ROOT": str(plugin)})
    assert ctx.plugin_root == plugin
    assert ctx.skill_dir == plugin / "skills" / "ro-crate-run"
