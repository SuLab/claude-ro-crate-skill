from __future__ import annotations

from ro_crate_run.validation.validator import _LEVELS, _RECOMMENDATIONS, CHECKS


def test_levels_are_derived_from_checks_order() -> None:
    # _LEVELS is the de-duplicated ordered set of the level names the checkers emit.
    expected = tuple(dict.fromkeys(name for name, _ in CHECKS))
    assert _LEVELS == expected


def test_levels_match_documented_pipeline() -> None:
    assert _LEVELS == ("journal", "state", "ro_crate", "profile", "reproducibility", "privacy")


def test_shacl_collapses_into_ro_crate_level() -> None:
    # SHACL is registered under the ro_crate level; no bare "shacl" level is emitted.
    assert "shacl" not in _LEVELS
    names = [name for name, _ in CHECKS]
    assert names.count("ro_crate") == 2  # check_rocrate + check_shacl


def test_every_check_is_callable() -> None:
    for name, fn in CHECKS:
        assert callable(fn)
        assert isinstance(name, str)


def test_recommendations_have_no_required_duplicate_keys() -> None:
    # The base/_required pairs are collapsed; lookup strips the suffix.
    assert not any(code.endswith("_required") for code in _RECOMMENDATIONS)


def test_required_finding_reuses_base_recommendation() -> None:
    from ro_crate_run.models import ValidationFinding

    # A policy-required reproducibility finding maps to the base recommendation
    # via the _required suffix strip.
    base = "missing_git_commit"
    required = ValidationFinding("reproducibility", f"{base}_required", "x")
    assert required.code.removesuffix("_required") == base
    assert base in _RECOMMENDATIONS
