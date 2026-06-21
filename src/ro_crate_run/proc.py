"""Hardened external-command runner shared by git and software probing.

Every external tool invocation in the capture path (git state, ``--version``
probes) must degrade rather than block or crash: a missing binary, a hung
process, or a non-zero exit are all "tool unavailable" outcomes here. Centralising
the text/capture/check=False/timeout policy keeps that robustness contract in one
place instead of being re-implemented per caller with subtly different guards.
"""

from __future__ import annotations

import subprocess


def run_capture(
    argv: list[str], *, timeout: float, cwd: str | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Run ``argv`` capturing text stdout/stderr, or ``None`` if it did not succeed.

    Returns the completed process only on a zero exit; returns ``None`` on a
    non-zero exit, on ``OSError`` (e.g. the binary is missing), or on
    ``TimeoutExpired`` (the command exceeded ``timeout`` seconds). Callers read
    ``stdout``/``stderr`` off the result and apply their own success semantics.
    """
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed if completed.returncode == 0 else None
