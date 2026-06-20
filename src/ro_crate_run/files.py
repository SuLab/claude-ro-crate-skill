from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def file_record(path: Path, project_root: Path, max_hash_bytes: int) -> dict[str, object]:
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
        "date_modified": __import__("datetime")
        .datetime.fromtimestamp(stat.st_mtime, __import__("datetime").timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
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


