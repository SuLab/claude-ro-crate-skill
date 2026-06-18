from __future__ import annotations

from pathlib import Path

import pytest


def test_skill_allowed_tools_not_blanket_python(repo_root: Path) -> None:
    text = (repo_root / "skills" / "ro-crate-run" / "SKILL.md").read_text()
    frontmatter = text.split("---", 2)[1]
    assert "Bash(python3 *)" not in frontmatter, "blanket python3 lets Claude bypass capture"
    assert "Bash(rcr *)" in frontmatter


def test_skill_assets_in_sync(repo_root: Path) -> None:
    a = (repo_root / "skills" / "ro-crate-run" / "SKILL.md").read_text()
    b = (
        repo_root
        / "src"
        / "ro_crate_run"
        / "assets"
        / "skills"
        / "ro-crate-run"
        / "SKILL.md"
    ).read_text()
    assert a == b


def test_admin_skill_disables_model_invocation(repo_root: Path) -> None:
    path = repo_root / "skills" / "ro-crate-run-admin" / "SKILL.md"
    assert path.exists()
    frontmatter = path.read_text().split("---", 2)[1]
    assert "disable-model-invocation: true" in frontmatter


REFERENCES = ["mapping-policy", "profile-selection", "validation-rules", "privacy-policy"]


@pytest.mark.parametrize("name", REFERENCES)
def test_reference_doc_has_substance(repo_root: Path, name: str) -> None:
    src = repo_root / "skills" / "ro-crate-run" / "references" / f"{name}.md"
    asset = (
        repo_root
        / "src"
        / "ro_crate_run"
        / "assets"
        / "skills"
        / "ro-crate-run"
        / "references"
        / f"{name}.md"
    )
    body = src.read_text()
    assert len(body.splitlines()) >= 20, f"{name} is still a stub"
    assert src.read_text() == asset.read_text(), f"{name} asset out of sync"
