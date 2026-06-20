import json
from pathlib import Path

from ro_crate_run import commands
from ro_crate_run.config import default_config
from ro_crate_run.constants import PROFILE_URIS


def test_start_creates_default_redaction_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert commands.start("Demo", "monitored", "process", no_checkpoint=True) == 0
    policy = tmp_path / ".ro-crate-run" / "secrets-redaction.json"
    assert policy.exists()
    data = json.loads(policy.read_text())
    assert "patterns" in data and isinstance(data["patterns"], list)


def test_default_config_matches_spec() -> None:
    cfg = default_config(project_name="demo")
    assert cfg.mode == "monitored"
    assert cfg.default_profile == "process"
    assert cfg.profile_uri == PROFILE_URIS["process"]
    assert cfg.privacy.include_prompts is False
    assert cfg.file_policy.include_event_journal is False
