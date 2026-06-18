"""Real-world scenarios driving the actual claude CLI. Gated by RCR_E2E=1."""
from __future__ import annotations

import os
import shutil

import pytest

from tests.e2e import assertions as A
from tests.e2e import coverage
from tests.e2e.harness import protect_repo, run_scenario
from tests.e2e.scenarios import ALL_SCENARIOS

pytestmark = pytest.mark.skipif(
    os.environ.get("RCR_E2E") != "1",
    reason="real-world claude CLI tests; set RCR_E2E=1 to enable",
)


@pytest.fixture(scope="session", autouse=True)
def _protect_repo_source():  # type: ignore[no-untyped-def]
    """Keep the repo's source-of-truth read-only while real claude sessions run."""
    with protect_repo():
        yield


@pytest.mark.e2e
@pytest.mark.parametrize("spec", ALL_SCENARIOS, ids=lambda s: s.name)
def test_scenario(spec) -> None:
    result = run_scenario(spec)
    try:
        A.assert_crate(result)
    finally:
        shutil.rmtree(result.workdir, ignore_errors=True)


@pytest.mark.e2e
def test_declared_coverage_complete() -> None:
    """The union of all scenarios' coverage_tags must span the whole surface."""
    coverage.assert_full_coverage(ALL_SCENARIOS)
