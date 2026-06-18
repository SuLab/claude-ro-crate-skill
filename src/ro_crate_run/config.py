from __future__ import annotations

from .constants import PROFILE_URIS
from .models import RcrConfig


def default_config(
    project_name: str | None = None, mode: str = "monitored", profile: str = "process"
) -> RcrConfig:
    selected = "process" if profile == "auto" else profile
    return RcrConfig(
        mode=mode,
        default_profile=profile,
        project_name=project_name,
        profile_uri=PROFILE_URIS.get(selected, PROFILE_URIS["process"]),
    )
