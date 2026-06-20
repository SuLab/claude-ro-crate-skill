"""Self-contained project installer for the ``rcr install-project`` command.

Vendors the importable package, copies the plugin-layout assets (skills/hooks/
templates/contexts) into a target ``.claude/`` tree, and merges the RO-Crate hook
fragment into ``settings.json`` so wrappers + hooks resolve without a pip install.
This is install-time machinery only; nothing here participates in run capture or
materialization.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any, cast

# Permission bits OR-ed into copied executable assets (owner/group/other rwx, x).
_EXEC_MODE_BITS = 0o755


def _is_executable_asset(name: str) -> bool:
    """Whether a copied shipped asset must be made executable.

    Single source of truth so install_project and the tree walker agree on which
    assets get ``+x``: the ``rcr`` launcher and any ``*.py`` wrapper/hook script.
    """
    return name.endswith(".py") or name == "rcr"


def install_project(target: str, force: bool = False) -> int:
    target_root = Path(target).resolve()
    claude = target_root / ".claude"
    (claude / "skills").mkdir(parents=True, exist_ok=True)
    (claude / "hooks").mkdir(parents=True, exist_ok=True)
    # Both skills ship in the asset payload (CLAUDE.md sync table); install both.
    for skill_name in ("ro-crate-run", "ro-crate-run-admin"):
        dest_skill = claude / "skills" / skill_name
        if dest_skill.exists() and force:
            shutil.rmtree(dest_skill)
        if not dest_skill.exists():
            _copy_resource_tree(_asset_root() / "skills" / skill_name, dest_skill)
    for hook in (_asset_root() / "hooks").iterdir():
        if hook.name.startswith("rocrate_") and _is_executable_asset(hook.name):
            _copy_resource_file(hook, claude / "hooks" / hook.name, executable=True)
    # Vendor the importable package so wrappers/hooks work without a pip install.
    lib_dir = claude / "lib" / "ro_crate_run"
    if lib_dir.exists() and force:
        shutil.rmtree(lib_dir)
    if not lib_dir.exists():
        package_root = Path(__file__).resolve().parent
        _vendor_package(package_root, lib_dir)
    # Ensure the bootstrap shim is present alongside hooks (it ships in assets/hooks).
    boot_src = _asset_root() / "hooks" / "_bootstrap.py"
    _copy_resource_file(boot_src, claude / "hooks" / "_bootstrap.py", executable=False)
    settings_fragment = _read_json_resource(_asset_root() / "templates" / "settings.rocrate.json")
    settings_rocrate_path = claude / "settings.rocrate.json"
    settings_rocrate_path.write_text(json.dumps(settings_fragment, indent=2, sort_keys=True) + "\n")
    settings_path = claude / "settings.json"
    existing = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    merged = _merge_settings(existing, settings_fragment)
    settings_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    print("Project files installed and .claude/settings.json updated.")
    return 0


def _asset_root() -> Any:
    source_root = Path(__file__).resolve().parents[2]
    source_assets = source_root / "src" / "ro_crate_run" / "assets"
    if source_assets.exists():
        return source_assets
    return resources.files("ro_crate_run") / "assets"


def _read_json_resource(path: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _mirror_tree(
    source: Any,
    destination: Path,
    *,
    exclude: Callable[[Any], bool] | None = None,
    executable: Callable[[str], bool] | None = None,
) -> None:
    """Recursively copy ``source`` into ``destination`` via ``write_bytes`` per file.

    The single tree-walker shared by every install copy path: skips entries for
    which ``exclude`` returns True, and marks a copied file executable when
    ``executable(name)`` returns True. Recurses into subdirectories so traversal
    is depth-agnostic (a future contexts/ subdir is carried automatically).
    """
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if exclude is not None and exclude(item):
            continue
        target = destination / item.name
        if item.is_dir():
            _mirror_tree(item, target, exclude=exclude, executable=executable)
        else:
            is_exec = executable(item.name) if executable is not None else False
            _copy_resource_file(item, target, executable=is_exec)


def _copy_resource_tree(source: Any, destination: Path) -> None:
    _mirror_tree(source, destination, executable=_is_executable_asset)


def _copy_resource_file(source: Any, destination: Path, *, executable: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    if executable:
        destination.chmod(destination.stat().st_mode | _EXEC_MODE_BITS)


def _vendor_package(package_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in package_root.rglob("*.py"):
        rel = item.relative_to(package_root)
        if rel.parts and rel.parts[0] in {"assets"}:
            continue
        if "__pycache__" in rel.parts:
            continue
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.read_bytes())
    # The plugin-layout assets (hooks/skills/templates) are installed separately into
    # .claude/ and are deliberately NOT vendored here, but the package MUST carry the
    # top-level assets/ files and assets/contexts/ — validation's L2 JSON-LD expansion
    # loads the vendored RO-Crate / workflow-run contexts via
    # resources.files("ro_crate_run") / "assets" / "contexts". Without them a vendored
    # (.claude/lib) deployment cannot expand JSON-LD and L2 validation breaks. The
    # contexts/ subtree is mirrored recursively so a future nested dir is carried too.
    assets_src = package_root / "assets"
    if assets_src.is_dir():
        for item in assets_src.iterdir():
            if item.is_file() and "__pycache__" not in item.parts:
                _copy_resource_file(item, destination / "assets" / item.name)
    contexts_src = assets_src / "contexts"
    if contexts_src.is_dir():
        _mirror_tree(
            contexts_src,
            destination / "assets" / "contexts",
            exclude=_exclude_pycache,
        )


def _exclude_pycache(item: Any) -> bool:
    """Exclude predicate for ``_mirror_tree``: skip ``__pycache__`` entries."""
    return "__pycache__" in item.parts


def _merge_settings(existing: dict[str, Any], fragment: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    existing_hooks = cast(dict[str, Any], merged.setdefault("hooks", {}))
    for event_name, hook_entries in cast(dict[str, Any], fragment.get("hooks", {})).items():
        current = list(existing_hooks.get(event_name, []))
        for hook_entry in cast(list[Any], hook_entries):
            if hook_entry not in current:
                current.append(hook_entry)
        existing_hooks[event_name] = current
    return merged
