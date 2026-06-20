from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Return the current UTC instant as an ISO-8601 string with microseconds and a 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def utc_now_compact() -> str:
    """Return the current UTC instant as a compact 'YYYYMMDD_HHMMSS' stamp (for filenames/ids)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def iso_utc_from_timestamp(epoch: float) -> str:
    """Render a POSIX timestamp as an ISO-8601 UTC string with a 'Z' suffix (no fixed timespec)."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
