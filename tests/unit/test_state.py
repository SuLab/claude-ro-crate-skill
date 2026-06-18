from __future__ import annotations

from ro_crate_run.config import default_config
from ro_crate_run.state import initial_state


def test_initial_state_has_session_id_field_defaulting_none() -> None:
    state = initial_state("Demo", default_config())
    assert state.session_id is None


def test_initial_state_profile_confidence_defaults_low() -> None:
    state = initial_state("Demo", default_config())
    assert state.profile_confidence == "low"
