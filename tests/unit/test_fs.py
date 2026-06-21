from __future__ import annotations

from pathlib import Path

from ro_crate_run.fs import file_record, sha256_file


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("hello\n")
    assert (
        sha256_file(path)
        == "sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )


def test_large_file_skip_reason(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * 1024)
    record = file_record(path, project_root=tmp_path, max_hash_bytes=10)
    assert record["hash_status"] == "skipped"
    assert record["hash_skip_reason"] == "larger_than_policy"


def test_symlink_outside_root_resolves_out_of_root(tmp_path: Path) -> None:
    # The production file resolver (_safe_resolve, used by plan_file_inclusion) rejects a
    # symlink whose target escapes the project root, so it becomes an out-of-root reference
    # and is never copied into the crate.
    from ro_crate_run.materialize.files import _safe_resolve

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)
    assert _safe_resolve(Path("link.txt"), tmp_path) is None


def test_symlink_to_regular_file_is_hashed(tmp_path: Path) -> None:
    # A symlink resolving to a regular file under the size gate must be hashed, not dropped as
    # not_regular_file: is_symlink() is now tested before is_dir(), and the resolved target's
    # content hash is captured for reproducibility evidence.
    target = tmp_path / "data.txt"
    target.write_text("hello\n")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    record = file_record(link, project_root=tmp_path, max_hash_bytes=1024)
    assert record["kind"] == "symlink"
    assert record["hash_status"] == "hashed"
    assert record["sha256"] == sha256_file(target)


def test_capture_diff_returns_none_outside_repo(tmp_path: Path) -> None:
    from ro_crate_run.git import capture_diff

    assert capture_diff(tmp_path) is None
