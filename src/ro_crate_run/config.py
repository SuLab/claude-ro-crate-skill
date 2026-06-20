"""Construct the default ``RcrConfig`` written to config.json for a new run."""

from __future__ import annotations

from .constants import resolve_profile
from .models import RcrConfig


def default_config(
    project_name: str | None = None, mode: str = "monitored", profile: str = "process"
) -> RcrConfig:
    """Return the baseline config for a new run, resolving the profile to its URI."""
    _, profile_uri = resolve_profile(profile)
    return RcrConfig(
        mode=mode,
        default_profile=profile,
        project_name=project_name,
        profile_uri=profile_uri,
    )
