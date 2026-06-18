from __future__ import annotations

from pathlib import Path

from ro_crate_run.files import file_record, sha256_file, should_copy_file


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


def test_symlink_outside_root_is_not_copied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)
    assert should_copy_file(link, project_root=tmp_path, explicit_permission=False) is False


def test_capture_diff_returns_none_outside_repo(tmp_path: Path) -> None:
    from ro_crate_run.git import capture_diff

    assert capture_diff(tmp_path) is None
