from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden._compare import find_secret_leaks
from tests.golden._fixtures import privacy_public


def test_public_crate_has_no_private_note_or_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    crate_dir = privacy_public(tmp_path)
    leaks = find_secret_leaks(crate_dir, needles=["secret-prompt", "PRIVATE"])
    assert leaks == [], f"public crate leaked private/secret content: {leaks}"
    # the public note SHOULD be present
    text = (crate_dir / "ro-crate-metadata.json").read_text()
    assert "Public summary note" in text
