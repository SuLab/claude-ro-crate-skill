"""Compact run-summary projection written alongside the crate as run-summary.json."""

from __future__ import annotations

from dataclasses import asdict

from ro_crate_run.models import RunModel


def run_summary(model: RunModel) -> dict[str, object]:
    """Return the run-summary dict written to run-summary.json in the crate directory.

    Scope: a deliberately compact, human-facing index of the run, NOT a complete
    projection of the RunModel. The authoritative, exhaustive record is
    ro-crate-metadata.json; this file exists for a quick at-a-glance read.

    Selection rule: identity (run_id/title), the resolved profile + URI, an event
    tally, and the run's primary I/O surface (declared commands, inputs, outputs).
    Everything else the RunModel carries — steps, phases, decisions, file_actions,
    raw_commands, subagents, blocked_actions, prompts, git/environment/containers/
    dependencies, and the run-level ``aborted`` flag — is intentionally omitted
    here and read from the crate graph instead. ``commands`` is normalized via
    ``asdict`` (CommandRecord dataclasses); ``inputs``/``outputs`` are already
    plain JSON dicts in the model and are passed through as-is.
    """
    return {
        "run_id": model.run_id,
        "title": model.title,
        "profile": model.selected_profile,
        "profile_uri": model.profile_uri,
        "event_count": len(model.events),
        "commands": [asdict(command) for command in model.commands],
        "inputs": model.inputs,
        "outputs": model.outputs,
    }
