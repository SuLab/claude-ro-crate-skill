from __future__ import annotations

from ro_crate_run.validation.graphview import (
    as_list,
    is_action,
    is_action_value,
    types_of,
)


def test_as_list_wraps_scalar() -> None:
    assert as_list("x") == ["x"]


def test_as_list_passes_list_through() -> None:
    same = ["a", "b"]
    assert as_list(same) is same


def test_as_list_wraps_none() -> None:
    assert as_list(None) == [None]


def test_types_of_scalar_type() -> None:
    assert types_of({"@type": "CreateAction"}) == ["CreateAction"]


def test_types_of_list_type() -> None:
    assert types_of({"@type": ["File", "Dataset"]}) == ["File", "Dataset"]


def test_types_of_missing_type() -> None:
    assert types_of({"@id": "x"}) == []


def test_is_action_true_for_scalar() -> None:
    assert is_action({"@type": "CreateAction"}) is True


def test_is_action_true_in_list() -> None:
    assert is_action({"@type": ["Thing", "ControlAction"]}) is True


def test_is_action_false_for_non_action() -> None:
    assert is_action({"@type": ["File", "Dataset"]}) is False


def test_is_action_false_for_missing_type() -> None:
    assert is_action({"@id": "x"}) is False


def test_is_action_value_accepts_raw_scalar() -> None:
    assert is_action_value("UpdateAction") is True
    assert is_action_value("File") is False


def test_is_action_value_accepts_raw_list() -> None:
    assert is_action_value(["File", "DeleteAction"]) is True


def test_is_action_value_coerces_non_string_members() -> None:
    # str() coercion guards against non-string @type members.
    assert is_action_value([None, 123]) is False
