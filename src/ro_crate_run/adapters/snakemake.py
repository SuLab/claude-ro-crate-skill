from __future__ import annotations

from pathlib import Path


def identify(path: Path) -> dict[str, object] | None:
    if path.name == "Snakefile" or path.suffix == ".smk":
        steps = [
            line.split()[1].rstrip(":")
            for line in path.read_text().splitlines()
            if line.strip().startswith("rule ")
        ]
        return {"engine": "snakemake", "path": str(path), "steps": steps}
    return None
