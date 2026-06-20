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
from importlib import resources
from pathlib import Path
from typing import Any, cast


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
        if hook.name.startswith("rocrate_") and hook.name.endswith(".py"):
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


def _copy_resource_tree(source: Any, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            _copy_resource_tree(item, target)
        else:
            executable = item.name.endswith(".py") or item.name == "rcr"
            _copy_resource_file(item, target, executable=executable)


def _copy_resource_file(source: Any, destination: Path, *, executable: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    if executable:
        destination.chmod(destination.stat().st_mode | 0o755)


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
    # The plugin-layout assets (hooks/skills/templates) are installed separately, but the
    # vendored package itself MUST carry assets/contexts/ — validation's L2 JSON-LD
    # expansion loads the vendored RO-Crate / workflow-run contexts via
    # resources.files("ro_crate_run") / "assets" / "contexts". Without them a vendored
    # (.claude/lib) deployment cannot expand JSON-LD and L2 validation breaks.
    for rel_dir in (Path("assets"), Path("assets") / "contexts"):
        src_dir = package_root / rel_dir
        if not src_dir.is_dir():
            continue
        for item in src_dir.iterdir():
            if item.is_file() and "__pycache__" not in item.parts:
                target = destination / rel_dir / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.read_bytes())


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
