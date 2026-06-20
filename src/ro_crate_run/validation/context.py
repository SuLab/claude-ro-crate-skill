"""Build the shared ValidationContext consumed by every validation level:
loads state/config, reads the journal safely, reads the crate metadata, and
exposes a cached entity index keyed by ``@id``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from ro_crate_run.models import RcrConfig, RcrState
from ro_crate_run.recovery import is_active_run
from ro_crate_run.state import load_config, load_state, read_events_safe


@dataclass
class ValidationContext:
    state_dir: Path
    state: RcrState
    cfg: RcrConfig
    events: list[dict[str, Any]]
    metadata: dict[str, Any] | None
    active_run: bool
    strict: bool
    public: bool
    journal_parse_error: str | None = None
    crate_dir: Path | None = None

    @cached_property
    def entities(self) -> dict[Any, dict[str, Any]]:
        """The crate ``@graph`` indexed by ``@id`` (empty when no metadata)."""
        return {e.get("@id"): e for e in (self.metadata or {}).get("@graph", [])}


def _read_metadata(state_dir: Path) -> dict[str, Any] | None:
    path = state_dir / "ro-crate" / "ro-crate-metadata.json"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except json.JSONDecodeError:
        return None


def build_context(
    state_dir: Path,
    *,
    strict: bool,
    public: bool,
    crate_dir: Path | None = None,
) -> ValidationContext:
    state = load_state(state_dir)
    cfg = load_config(state_dir)
    events, parse_error = read_events_safe(state_dir)
    active = is_active_run(events)
    return ValidationContext(
        state_dir=state_dir,
        state=state,
        cfg=cfg,
        events=events,
        metadata=_read_metadata(state_dir),
        active_run=active,
        strict=strict or cfg.validation.strict,
        public=public,
        journal_parse_error=parse_error,
        crate_dir=crate_dir,
    )
