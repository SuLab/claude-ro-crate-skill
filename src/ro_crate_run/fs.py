"""Filesystem primitives: content hashing and file-metadata records for crate file entities."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any

from . import clock

# The digest prefix that distinguishes a sha256 hex string in records and crate entities.
_SHA256_PREFIX = "sha256:"


def bare_sha256(value: str) -> str:
    """Return the bare hex digest, stripping a leading 'sha256:' prefix if present."""
    if value.startswith(_SHA256_PREFIX):
        return value[len(_SHA256_PREFIX) :]
    return value


def prefixed_sha256(value: str) -> str:
    """Return the digest with exactly one leading 'sha256:' prefix."""
    return _SHA256_PREFIX + bare_sha256(value)


def write_json(path: Path, obj: Any) -> None:
    """Write obj as canonical pretty JSON (2-space indent, sorted keys, trailing newline)."""
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    """Hash a file's contents and return the 'sha256:'-prefixed hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return prefixed_sha256(digest.hexdigest())


def file_record(path: Path, project_root: Path, max_hash_bytes: int) -> dict[str, object]:
    """Return a file-metadata record describing path for crate file entities.

    Keys (and their possible values):
      - path (str): the input path as given.
      - relative_path (str | None): path relative to project_root, or None if outside it.
      - exists (bool): whether the path exists.
      - kind (str): one of 'directory', 'symlink', 'file', or 'missing' (when exists is False).
      - hash_status (str): one of 'missing', 'hashed', or 'skipped'.
      - hash_skip_reason (str): present only when hash_status == 'skipped'; one of
        'larger_than_policy' (file exceeds max_hash_bytes) or 'not_regular_file'.
      - content_size (int): byte size from stat; present only when the path exists.
      - date_modified (str): mtime as an ISO-8601 UTC string with a 'Z' suffix; present only
        when the path exists.
      - encoding_format (str): guessed MIME type, defaulting to 'application/octet-stream';
        present only when the path exists.
      - sha256 (str): 'sha256:'-prefixed digest; present only when a regular file was hashed.
    """
    path = Path(path)
    exists = path.exists()
    resolved = path.resolve() if exists else path
    try:
        relative = str(resolved.relative_to(project_root.resolve()))
    except ValueError:
        relative = None
    if not exists:
        return {
            "path": str(path),
            "relative_path": relative,
            "exists": False,
            "kind": "missing",
            "hash_status": "missing",
        }
    kind = "directory" if path.is_dir() else "symlink" if path.is_symlink() else "file"
    stat = path.stat()
    mime, _ = mimetypes.guess_type(str(path))
    record: dict[str, object] = {
        "path": str(path),
        "relative_path": relative,
        "exists": True,
        "kind": kind,
        "content_size": stat.st_size,
        "date_modified": clock.iso_utc_from_timestamp(stat.st_mtime),
        "encoding_format": mime or "application/octet-stream",
    }
    if kind == "file" and stat.st_size <= max_hash_bytes:
        record["sha256"] = sha256_file(path)
        record["hash_status"] = "hashed"
    elif kind == "file":
        record["hash_status"] = "skipped"
        record["hash_skip_reason"] = "larger_than_policy"
    else:
        record["hash_status"] = "skipped"
        record["hash_skip_reason"] = "not_regular_file"
    return record
