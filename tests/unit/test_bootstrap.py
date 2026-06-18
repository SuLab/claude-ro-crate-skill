from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest


def _load_bootstrap(repo_root: Path):  # type: ignore[no-untyped-def]
    path = repo_root / "skills" / "ro-crate-run" / "scripts" / "_bootstrap.py"
    spec = importlib.util.spec_from_file_location("_bootstrap_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_find_package_root_via_env(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap = _load_bootstrap(repo_root)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo_root))
    found = bootstrap.find_package_root()
    assert found is not None
    assert (found / "ro_crate_run" / "__init__.py").exists()


def test_ensure_on_path_imports_package(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap = _load_bootstrap(repo_root)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo_root))
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "ro_crate_run" not in p])
    bootstrap.ensure_on_path()
    assert any((Path(p) / "ro_crate_run" / "__init__.py").exists() for p in sys.path)


def test_all_wrappers_import_bootstrap(repo_root: Path) -> None:
    targets = list((repo_root / "skills" / "ro-crate-run" / "scripts").glob("rocrate_*.py"))
    targets.append(repo_root / "skills" / "ro-crate-run" / "scripts" / "rcr")
    targets.extend((repo_root / "hooks").glob("rocrate_*.py"))
    offenders = []
    for path in targets:
        text = path.read_text()
        if not re.search(r"^import _bootstrap", text, re.MULTILINE):
            offenders.append(str(path.relative_to(repo_root)))
    assert offenders == [], f"wrappers missing bootstrap: {offenders}"
