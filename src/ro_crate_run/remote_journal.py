"""Best-effort mirror of journal event lines to a remote or local sink.

The local journal is always authoritative; mirroring is append-only and
non-fatal so provenance capture continues even when the configured remote is
unreachable. Set ``remote_journal.fail_closed`` to have the writer surface a
mirror failure instead of swallowing it.
"""

from __future__ import annotations

from pathlib import Path

from .models import RemoteJournalConfig


def mirror_event(cfg: RemoteJournalConfig, event_line: str) -> bool:
    """Best-effort append of one NDJSON event line to a remote/local mirror.

    Append-only and non-fatal: any failure returns False rather than raising,
    so provenance capture continues even when the mirror is unreachable.
    """
    if not cfg.enabled:
        return False
    try:
        if not cfg.endpoint:
            return False
        if cfg.type == "file":
            target_path = Path(cfg.endpoint)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("a", encoding="utf-8") as handle:
                handle.write(event_line.rstrip("\n") + "\n")
            return True
        if cfg.type == "http":
            import urllib.request

            request = urllib.request.Request(
                cfg.endpoint,
                data=(event_line.rstrip("\n") + "\n").encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/x-ndjson"},
            )
            with urllib.request.urlopen(request, timeout=cfg.timeout_seconds):
                return True
        return False
    except OSError:
        return False
