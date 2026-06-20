"""export_zip must DEFLATE every entry and stay byte-deterministic (A2 regression).

writestr honors the ZipInfo's own compress_type, which defaults to ZIP_STORED, so
a fresh ZipInfo per entry shipped uncompressed despite the ZipFile-level
compression=ZIP_DEFLATED. Each entry must set compress_type explicitly.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from ro_crate_run.export import export_zip


def _build_crate(crate_dir: Path) -> str:
    """Stage a crate with one highly compressible entry; return its archive name."""
    crate_dir.mkdir(parents=True, exist_ok=True)
    rel = "ro-crate-metadata.json"
    # Repetitive, non-trivial payload so DEFLATE measurably beats STORED.
    (crate_dir / rel).write_text("A" * 10_000)
    return rel


def test_export_zip_entries_are_deflated(tmp_path: Path) -> None:
    crate_dir = tmp_path / "crate"
    rel = _build_crate(crate_dir)

    out = export_zip(crate_dir, tmp_path / "out.zip")

    with zipfile.ZipFile(out) as archive:
        info = archive.getinfo(rel)
        assert info.compress_type == zipfile.ZIP_DEFLATED
        # Compression actually took effect, not just the flag.
        assert info.compress_size < info.file_size


def test_export_zip_is_deterministic(tmp_path: Path) -> None:
    crate_a = tmp_path / "a"
    crate_b = tmp_path / "b"
    _build_crate(crate_a)
    _build_crate(crate_b)

    zip_a = export_zip(crate_a, tmp_path / "a.zip")
    zip_b = export_zip(crate_b, tmp_path / "b.zip")

    # Identical crates compress to byte-identical archives.
    assert Path(zip_a).read_bytes() == Path(zip_b).read_bytes()
