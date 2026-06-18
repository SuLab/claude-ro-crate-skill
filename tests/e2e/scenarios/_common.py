"""Shared constants and helpers for scenario modules (kept separate to avoid import cycles)."""
from __future__ import annotations

PROCESS_URI = "https://w3id.org/ro/wfrun/process/0.5"
WORKFLOW_URI = "https://w3id.org/ro/wfrun/workflow/0.5"
PROVENANCE_URI = "https://w3id.org/ro/wfrun/provenance/0.5"

# Prepended (via --append-system-prompt) to prescriptive scenarios so the agent runs the
# listed rcr commands verbatim, making the captured provenance deterministic.
STRICT_PREAMBLE = (
    "You are capturing provenance with the ro-crate-run skill. Run EXACTLY the rcr "
    "commands listed in the user message, in order, verbatim. Do not add, skip, "
    "reorder, or substitute commands. Use the bundled rcr CLI. When a step says to "
    "create a file, create it. After the last command, stop. Do not finalize or export "
    "unless explicitly told to."
)


def prescriptive_prompt(intro: str, commands: list[str]) -> str:
    """Build a numbered, verbatim command list prompt for a prescriptive scenario."""
    lines = [intro, "", "Run EXACTLY these commands in order:"]
    lines += [f"{i}. {c}" for i, c in enumerate(commands, start=1)]
    return "\n".join(lines)
