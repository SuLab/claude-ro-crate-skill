from __future__ import annotations

from pathlib import Path

import pytest

from ro_crate_run import preview
from ro_crate_run.cli import main


def test_render_includes_commands_and_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Preview Demo", "--profile", "process", "--no-checkpoint"]) == 0
    assert (
        main(
            ["run", "--outputs", "out.txt", "--", "python3", "-c", "open('out.txt','w').write('ok')"]
        )
        == 0
    )
    assert main(["checkpoint"]) == 0
    html_text = preview.render(tmp_path / ".ro-crate-run")
    assert "Preview Demo" in html_text
    assert "out.txt" in html_text
    assert "python3" in html_text
    assert "$command_rows" not in html_text  # all placeholders substituted
