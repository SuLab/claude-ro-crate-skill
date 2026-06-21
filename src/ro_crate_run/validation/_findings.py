"""The one constructor for a ``ValidationFinding`` shared by every level checker.

Each checker binds its own level once (e.g. ``partial(level_finding, LEVEL_JOURNAL)``)
so the level string is named in a single place per module instead of being repeated on
every emission. The factory keeps the ``ValidationFinding`` field order and the
``severity="error"`` default identical to constructing the finding directly, so the
emitted (level, code, message, path, severity) tuples — and therefore the persisted
validation report — are unchanged.
"""

from __future__ import annotations

from ro_crate_run.models import ValidationFinding


def level_finding(
    level: str,
    code: str,
    message: str,
    path: str = "",
    severity: str = "error",
) -> ValidationFinding:
    """Build a ``ValidationFinding`` under ``level`` (an error by default).

    Callers bind ``level`` with ``functools.partial`` to get a checker-local
    finding constructor; ``severity="warning"`` is passed for the advisory findings.
    """
    return ValidationFinding(level, code, message, path, severity)
