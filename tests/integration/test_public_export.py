from __future__ import annotations

import json as _json
import zipfile
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.hooks import handle_hook


def test_finalize_public_excludes_event_journal_and_prompts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Public demo", "--no-checkpoint"]) == 0
    assert main(["note", "Public summary", "--public"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )

    assert main(["finalize", "--zip", "--public"]) == 0

    crate_dir = tmp_path / ".ro-crate-run/ro-crate"
    metadata = _json.loads((crate_dir / "ro-crate-metadata.json").read_text())
    graph_ids = {entity["@id"] for entity in metadata["@graph"]}
    assert ".ro-crate-run/events.ndjson" not in graph_ids
    zip_files = list((tmp_path / ".ro-crate-run").glob("*.zip"))
    assert len(zip_files) == 1
    with zipfile.ZipFile(zip_files[0]) as archive:
        assert "ro-crate-metadata.json" in archive.namelist()
        assert "events.ndjson" not in archive.namelist()


def test_finalize_public_fails_on_prompt_in_included_journal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    handle_hook("UserPromptSubmit", {"prompt": "please use my data"})
    # Journal embedded + prompts present, neither explicitly enabled in config → must fail.
    assert main(["finalize", "--public", "--include-event-journal"]) == 1
    assert list((tmp_path / ".ro-crate-run").glob("*.zip")) == []


def test_public_by_default_makes_unflagged_finalize_public(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    cfg_path = state_dir / "config.json"
    cfg = _json.loads(cfg_path.read_text())
    cfg["privacy"]["public_by_default"] = True
    cfg_path.write_text(_json.dumps(cfg))
    # Plant a secret in the crate; an unflagged finalize must run the public gate and fail.
    (state_dir / "ro-crate" / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    assert main(["finalize"]) == 1


def test_finalize_public_fails_on_secret_in_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["output", "out.txt", "--copy", "--required"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('AKIAIOSFODNN7EXAMPLE')",
            ]
        )
        == 0
    )
    assert main(["finalize", "--public"]) == 1


def test_finalize_public_clean_crate_succeeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["output", "out.txt", "--copy", "--required"]) == 0
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('ok')",
            ]
        )
        == 0
    )
    assert main(["finalize", "--public", "--zip"]) == 0
    assert len(list((tmp_path / ".ro-crate-run").glob("*.zip"))) == 1


def test_finalize_public_fails_on_included_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.py").write_text("print('hi')\n")
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["output", "src/lib.py", "--copy", "--required"]) == 0
    assert main(["run", "--", "python3", "-c", "print('done')"]) == 0
    assert main(["finalize", "--public"]) == 1
