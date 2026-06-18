"""Offline sanity check on the coverage-matrix surface (no claude, always runs).

The full completeness gate (declared tags span the whole surface) lives in
`test_e2e_scenarios.py` behind RCR_E2E, and `run.py` additionally enforces coverage
over scenarios that actually pass against the real claude CLI.
"""
from __future__ import annotations

from tests.e2e import coverage


def test_required_tags_nonempty() -> None:
    assert len(coverage.REQUIRED_TAGS) > 50
