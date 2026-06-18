from __future__ import annotations

from pathlib import Path

from .models import RemoteJournalConfig


def mirror_event(cfg: RemoteJournalConfig, event_line: str) -> bool:
    """Best-effort append of one NDJSON event line to a remote/local mirror.

    Append-only and non-fatal: any failure returns False rather than raising,
    so provenance capture continues even when the mirror is unreachable.

    Supports both kind/target (plan naming) and type/endpoint (models.py naming)
    for the config fields.
    """
    if not getattr(cfg, "enabled", False):
        return False
    try:
        # Support both field naming conventions
        kind = getattr(cfg, "kind", None) or getattr(cfg, "type", None)
        target = getattr(cfg, "target", None) or getattr(cfg, "endpoint", None)
        if not target:
            return False
        if kind == "file":
            target_path = Path(target)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("a", encoding="utf-8") as handle:
                handle.write(event_line.rstrip("\n") + "\n")
            return True
        if kind == "http":
            import urllib.request

            timeout = int(getattr(cfg, "timeout_seconds", 5))
            request = urllib.request.Request(
                target,
                data=(event_line.rstrip("\n") + "\n").encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/x-ndjson"},
            )
            with urllib.request.urlopen(request, timeout=timeout):
                return True
        return False
    except OSError:
        return False
