from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

from .constants import PROFILE_URIS
from .models import (
    FilePolicy,
    HashPolicy,
    JsonDict,
    LastCheckpoint,
    PrivacyConfig,
    RcrConfig,
    RcrState,
    RedactionConfig,
    RemoteJournalConfig,
    ValidationConfig,
)
from .time import utc_now, utc_now_compact

T = TypeVar("T")


def ensure_runtime_dirs(state_dir: Path) -> None:
    for rel in ["logs", "commands", "hashes", "snapshots", "staging", "reports", "ro-crate"]:
        (state_dir / rel).mkdir(parents=True, exist_ok=True)


def initial_state(title: str, config: RcrConfig, now: str | None = None) -> RcrState:
    now = now or utc_now()
    suffix = secrets.token_hex(4)
    compact = now.replace("-", "").replace(":", "").replace("T", "_").split(".")[0].rstrip("Z")
    if len(compact) < 15:
        compact = utc_now_compact()
    selected = "process" if config.default_profile == "auto" else config.default_profile
    return RcrState(
        run_id=f"run_{compact}_{suffix}",
        title=title,
        created_at=now,
        updated_at=now,
        mode=config.mode,
        selected_profile=selected,
        requested_profile=config.default_profile,
        profile_uri=PROFILE_URIS.get(selected, PROFILE_URIS["process"]),
        privacy=config.privacy,
    )


def write_config(state_dir: Path, config: RcrConfig) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text(_to_json(config))


def load_config(state_dir: Path) -> RcrConfig:
    return _from_dict(RcrConfig, json.loads((state_dir / "config.json").read_text()))


def write_state(state_dir: Path, state: RcrState) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / "state.json.tmp"
    tmp.write_text(_to_json(state))
    tmp.replace(state_dir / "state.json")


def load_state(state_dir: Path) -> RcrState:
    return _from_dict(RcrState, json.loads((state_dir / "state.json").read_text()))


def update_state(state_dir: Path, mutate: Callable[[RcrState], None]) -> RcrState:
    """Atomically load -> mutate -> persist state.json under the run lock (SPEC §11.5),
    so a concurrent event append cannot clobber the update."""
    from filelock import FileLock

    with FileLock(str(Path(state_dir) / "lock")):
        state = load_state(state_dir)
        mutate(state)
        write_state(state_dir, state)
        return state


def write_id_map(state_dir: Path, id_map: dict[str, Any] | None = None) -> None:
    id_map = id_map or {
        "schema_version": "1.0.0",
        "event_to_entity": {},
        "path_to_entity": {},
        "step_to_entity": {},
        "profile_to_entity": {},
    }
    (state_dir / "id-map.json").write_text(json.dumps(id_map, indent=2, sort_keys=True) + "\n")


def read_events(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "events.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _to_json(value: Any) -> str:
    return json.dumps(_as_plain(value), indent=2, sort_keys=True) + "\n"


def _as_plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _as_plain(v) for k, v in asdict(cast(Any, value)).items()}
    if isinstance(value, dict):
        return {k: _as_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_plain(v) for v in value]
    return value


def _from_dict(cls: type[T], data: dict[str, Any]) -> T:
    kwargs: dict[str, Any] = {}
    for field_def in fields(cast(Any, cls)):
        if field_def.name not in data:
            continue
        value = data[field_def.name]
        typ = field_def.type
        if typ in (PrivacyConfig, "PrivacyConfig"):
            value = _from_dict(PrivacyConfig, value)
        elif typ in (FilePolicy, "FilePolicy"):
            value = _from_dict(FilePolicy, value)
        elif typ in (HashPolicy, "HashPolicy"):
            value = _from_dict(HashPolicy, value)
        elif typ in (RedactionConfig, "RedactionConfig"):
            value = _from_dict(RedactionConfig, value)
        elif typ in (ValidationConfig, "ValidationConfig"):
            value = _from_dict(ValidationConfig, value)
        elif typ in (RemoteJournalConfig, "RemoteJournalConfig"):
            value = _from_dict(RemoteJournalConfig, value)
        elif typ in (LastCheckpoint, "LastCheckpoint") or field_def.name == "last_checkpoint":
            value = _from_dict(LastCheckpoint, value) if value else None
        kwargs[field_def.name] = value
    return cls(**kwargs)


def record_known_output(state: RcrState, path: str, sha256: str | None) -> bool:
    entry: JsonDict = {"path": path, "sha256": sha256}
    for existing in state.known_outputs:
        if existing.get("path") == path:
            if existing.get("sha256") == sha256:
                return False
            existing["sha256"] = sha256
            return True
    state.known_outputs.append(entry)
    return True


def detect_output_changes(state_dir: Path, state: RcrState, max_bytes: int) -> bool:
    """Return True if any known output's on-disk content no longer matches its recorded
    sha256 (SPEC §12.2 dirty trigger: known output hashes changed)."""
    from .files import sha256_file

    project_dir = state_dir.parent
    for out in state.known_outputs:
        path = out.get("path")
        recorded = out.get("sha256")
        if not path or not recorded:
            continue
        target = project_dir / str(path)
        if target.is_file() and target.stat().st_size <= max_bytes:
            if sha256_file(target) != recorded:
                return True
    return False


def run_is_active(state_dir: Path) -> bool:
    # Thin convenience wrapper; delegates to the single source of truth to avoid a
    # second, drift-prone copy of the terminal-event logic.
    from .recovery import is_active_run
    return is_active_run(read_events(state_dir))
