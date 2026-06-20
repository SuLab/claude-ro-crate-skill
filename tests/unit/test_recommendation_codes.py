"""Guard test for the recommendation-lookup coupling (audit D4).

``validator._RECOMMENDATIONS`` is keyed by validation finding *codes* that are
minted as string literals in the per-level checker modules. The lookup strips a
trailing ``_required`` before matching, so the policy-required variant reuses the
base recommendation. Nothing structurally links a recommendation key to a real
code, so renaming a code silently drops its recommendation.

This test derives the set of codes the checkers can actually emit (by scanning
the checker modules for the string-literal ``code`` argument of every finding
factory) and asserts every ``_RECOMMENDATIONS`` key is a subset of it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ro_crate_run.validation.validator import _RECOMMENDATIONS

# Finding-factory call name -> positional index of its *code* argument.
# ValidationFinding(level, code, ...) and PrivacyFinding(severity, code, ...)
# take code second; the module helpers and the reproducibility ``warn`` closure
# take it first.
_CODE_ARG_INDEX = {
    "ValidationFinding": 1,
    "PrivacyFinding": 1,
    "_finding": 0,
    "_warning": 0,
    "warn": 0,
}


def _validation_pkg_dir() -> Path:
    import ro_crate_run.validation as pkg

    return Path(pkg.__file__).resolve().parent


def _emittable_codes() -> set[str]:
    """String-literal finding codes appearing at any factory call site across
    the validation package."""
    codes: set[str] = set()
    for module in sorted(_validation_pkg_dir().glob("*.py")):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            idx = _CODE_ARG_INDEX.get(node.func.id)
            if idx is None or len(node.args) <= idx:
                continue
            arg = node.args[idx]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                codes.add(arg.value)
    return codes


def test_extraction_finds_a_plausible_code_set() -> None:
    # Sanity guard on the AST scanner itself: if the factory names or arg
    # positions ever change, this floor catches a silently-empty extraction
    # (which would make the subset assertion vacuously pass).
    codes = _emittable_codes()
    assert len(codes) >= 40
    # Spot-check a few codes minted via different factory shapes.
    assert "secret_pattern" in codes  # PrivacyFinding + _finding
    assert "missing_input_hash" in codes  # _warning helper
    assert "missing_git_commit" in codes  # nested ``warn`` closure
    assert "metadata_missing" in codes  # _finding helper


def test_every_recommendation_key_maps_to_an_emittable_code() -> None:
    emittable = _emittable_codes()
    # Recommendations are keyed by the *base* code (the ``_required`` variant is
    # stripped at lookup), so a key may legitimately match either the base code
    # or its ``<code>_required`` form.
    orphans = sorted(
        key
        for key in _RECOMMENDATIONS
        if key not in emittable and f"{key}_required" not in emittable
    )
    assert orphans == [], (
        "recommendation keys with no emittable finding code (renamed/removed code "
        f"silently drops its recommendation): {orphans}"
    )


def test_no_recommendation_key_carries_required_suffix() -> None:
    # Lookup strips ``_required``; a key that already carries it could never be
    # hit. (Complements the same check in test_validation_registry.py, but keeps
    # this guard self-contained.)
    bad = sorted(k for k in _RECOMMENDATIONS if k.endswith("_required"))
    assert bad == [], f"_RECOMMENDATIONS keys must be base codes, found: {bad}"
