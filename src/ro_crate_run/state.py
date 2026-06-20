"""Load/persist the derived state.json cache and config.json.

state.json is recoverable from the append-only event journal and is never a
source of truth; it is a cache that the journal can always rebuild.
"""

from __future__ import annotations

import json
import secrets
import typing
from collections.abc import Callable, Iterator
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar, Union, cast, get_args, get_origin

from . import ids
from .constants import resolve_profile
from .fs import write_json
from .models import JsonDict, RcrConfig, RcrState
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
    selected, profile_uri = resolve_profile(config.default_profile)
    return RcrState(
        run_id=f"run_{compact}_{suffix}",
        title=title,
        created_at=now,
        updated_at=now,
        mode=config.mode,
        selected_profile=selected,
        requested_profile=config.default_profile,
        profile_uri=profile_uri,
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
    id_map = id_map or ids.new_id_map()
    write_json(state_dir / "id-map.json", id_map)


def _iter_journal_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield ``(1-based index, line)`` for every non-blank journal line.

    The single low-level scan the strict and safe readers share, so the
    blank-skip rule and ``utf-8`` decoding live in exactly one place.
    """
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            yield idx, line


def read_events(state_dir: Path) -> list[dict[str, Any]]:
    """Read every journal event, raising on a malformed line.

    Callers that reduce or repair the journal rely on this strict behavior; use
    :func:`read_events_safe` when a corrupted line should be reported instead.
    """
    path = state_dir / "events.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for _, line in _iter_journal_lines(path)]


def read_events_safe(state_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Read journal events, capturing the first parse error instead of raising.

    Returns the events parsed up to the first malformed line plus a human-readable
    error string (or ``None`` when every line parsed cleanly).
    """
    path = state_dir / "events.ndjson"
    if not path.exists():
        return [], None
    events: list[dict[str, Any]] = []
    for idx, line in _iter_journal_lines(path):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            return events, f"line {idx}: {exc}"
    return events, None


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


def _unwrap_optional(typ: Any) -> Any:
    """Return the inner type of ``Optional[T]`` / ``T | None``, else ``typ`` unchanged."""
    if get_origin(typ) is Union:
        non_none = [arg for arg in get_args(typ) if arg is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return typ


def _from_dict(cls: type[T], data: dict[str, Any]) -> T:
    """Reconstruct a config/state dataclass from its plain-dict JSON form.

    Each field's resolved type hint drives reconstruction: a nested dataclass
    field (including one wrapped in ``Optional``) is recursed into, while scalar
    and collection fields pass through unchanged. Only ``RcrConfig``/``RcrState``
    use this path; journal events are parsed separately.
    """
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for field_def in fields(cast(Any, cls)):
        if field_def.name not in data:
            continue
        value = data[field_def.name]
        typ = _unwrap_optional(hints.get(field_def.name, field_def.type))
        if isinstance(typ, type) and is_dataclass(typ):
            nested = cast("type[Any]", typ)
            if field_def.name == "last_checkpoint":
                # An empty/absent checkpoint persists as a falsy value, not a nested object.
                value = _from_dict(nested, value) if value else None
            elif value is not None:
                value = _from_dict(nested, value)
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
    from .fs import sha256_file

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
