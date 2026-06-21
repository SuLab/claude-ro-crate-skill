from __future__ import annotations

from pathlib import Path

from ro_crate_run.ids import IdMap


def test_entity_for_event_is_persisted_urn_uuid(tmp_path: Path) -> None:
    idmap = IdMap(tmp_path)
    first = idmap.entity_for_event("cmd_1")
    assert first.startswith("urn:uuid:")
    assert IdMap(tmp_path).entity_for_event("cmd_1") == first  # persisted & stable


def test_software_id_is_slugged_and_stable(tmp_path: Path) -> None:
    idmap = IdMap(tmp_path)
    sid = idmap.software_id("Python 3")
    assert sid == "#software/python-3"
    assert IdMap(tmp_path).software_id("Python 3") == sid


def test_entity_for_step_slugifies(tmp_path: Path) -> None:
    assert IdMap(tmp_path).entity_for_step("normalize data") == "#step/normalize-data"
