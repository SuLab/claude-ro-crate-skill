from __future__ import annotations

from pathlib import Path
from typing import cast

from . import cwl, galaxy, nextflow, snakemake

_ADAPTERS = (snakemake, cwl, nextflow, galaxy)


def detect_engine(path: Path) -> dict[str, object] | None:
    for adapter in _ADAPTERS:
        raw = adapter.identify(path)
        if raw is not None:
            return cast(dict[str, object], raw)
    return None


def extract_steps(path: Path) -> list[str]:
    result = detect_engine(path)
    if result is None:
        return []
    steps = result.get("steps", [])
    return list(steps) if isinstance(steps, list) else []
