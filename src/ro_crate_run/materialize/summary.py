from __future__ import annotations

from dataclasses import asdict

from ro_crate_run.models import RunModel


def run_summary(model: RunModel) -> dict[str, object]:
    """Return the run-summary dict written to run-summary.json in the crate directory."""
    return {
        "run_id": model.run_id,
        "title": model.title,
        "profile": model.selected_profile,
        "profile_uri": model.profile_uri,
        "event_count": len(model.events),
        "commands": [asdict(command) for command in model.commands],
        "inputs": model.inputs,
        "outputs": model.outputs,
        "warnings": [],
    }
