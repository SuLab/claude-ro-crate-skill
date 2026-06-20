from __future__ import annotations

from pathlib import Path

from ro_crate_run.ids import (
    ID_MAP_SCHEMA_VERSION,
    file_ref,
    new_id_map,
    relative_file_id,
)


def test_relative_file_id_inside_project_dir(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    target = project_dir / "sub" / "out.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    assert relative_file_id(target, project_dir) == "sub/out.txt"


def test_relative_file_id_out_of_root_absolute(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    outside = tmp_path / "elsewhere" / "data.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("y")
    result = relative_file_id(outside, project_dir)
    assert result == outside.resolve().as_uri()
    assert result.startswith("file://")


def test_relative_file_id_relative_path(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    assert relative_file_id(Path("rel/path.txt"), project_dir) == "rel/path.txt"


def test_file_ref_shape(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    target = project_dir / "a.txt"
    target.write_text("z")
    assert file_ref(target, project_dir) == {"@id": "a.txt"}


def test_new_id_map_keys_and_schema() -> None:
    id_map = new_id_map()
    assert id_map["schema_version"] == ID_MAP_SCHEMA_VERSION
    assert ID_MAP_SCHEMA_VERSION == "1.0.0"
    for key in (
        "event_to_entity",
        "path_to_entity",
        "step_to_entity",
        "profile_to_entity",
        "software_to_entity",
    ):
        assert id_map[key] == {}
    # Distinct dict instances, not shared references.
    id_map["event_to_entity"]["k"] = "v"
    assert new_id_map()["event_to_entity"] == {}
