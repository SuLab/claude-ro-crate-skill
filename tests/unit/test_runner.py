import json
from pathlib import Path

from ro_crate_run import commands
from ro_crate_run.cli import main
from ro_crate_run.runner import CommandRunner
from ro_crate_run.state import read_events


def _start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run", "--no-checkpoint"]) == 0


def test_run_streams_and_redacts_stdout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    commands.start("Demo", "monitored", "process", no_checkpoint=True)
    sd = tmp_path / ".ro-crate-run"
    rc = CommandRunner(sd, tmp_path).run(
        ["python3", "-c", "print('API_KEY=abcd1234supersecretvalue')"]
    )
    assert rc == 0
    log = next((sd / "logs").glob("*.stdout.txt")).read_text()
    assert "abcd1234supersecretvalue" not in log
    assert "[REDACTED:secret]" in log
    assert "redaction.applied" in [e["event_type"] for e in read_events(sd)]


def test_run_command_captures_sidecar_logs_and_exit_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Run command demo", "--no-checkpoint"]) == 0

    code = main(
        [
            "run",
            "--outputs",
            "out.txt",
            "--",
            "python3",
            "-c",
            "open('out.txt','w').write('ok\\n'); print('done')",
        ]
    )

    assert code == 0
    command_files = list((tmp_path / ".ro-crate-run/commands").glob("cmd_*.json"))
    assert len(command_files) == 1
    sidecar = json.loads(command_files[0].read_text())
    assert sidecar["argv"][:3] == [
        "python3",
        "-c",
        "open('out.txt','w').write('ok\\n'); print('done')",
    ]
    assert sidecar["outputs"] == ["out.txt"]
    stdout_files = list((tmp_path / ".ro-crate-run/logs").glob("cmd_*.stdout.txt"))
    assert stdout_files[0].read_text() == "done\n"

    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / ".ro-crate-run/events.ndjson").read_text().splitlines()
    ]
    assert "execution.command.started" in event_types
    assert "execution.command.completed" in event_types


def test_failed_command_returns_original_exit_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Failure demo", "--no-checkpoint"]) == 0
    code = main(
        ["run", "--", "python3", "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"]
    )
    assert code == 7


def test_missing_executable_records_failed_command(tmp_path: Path, monkeypatch) -> None:
    _start(tmp_path, monkeypatch)

    code = main(["run", "--", "definitely-not-a-real-rcr-command-xyz"])

    assert code == 127
    events = read_events(tmp_path / ".ro-crate-run")
    assert events[-1]["event_type"] == "execution.command.failed"
    assert events[-1]["payload"]["failure_class"] == "startup_error"
    sidecar = json.loads(
        sorted((tmp_path / ".ro-crate-run" / "commands").glob("*.json"))[-1].read_text()
    )
    assert sidecar["terminal_status"] == "failed"
    assert sidecar["failure_class"] == "startup_error"


def test_run_hashes_declared_inputs(tmp_path: Path, monkeypatch) -> None:
    _start(tmp_path, monkeypatch)
    (tmp_path / "in.txt").write_text("payload\n")
    assert main(["run", "--inputs", "in.txt", "--", "python3", "-c", "print(1)"]) == 0
    sidecars = sorted((tmp_path / ".ro-crate-run" / "commands").glob("*.json"))
    data = json.loads(sidecars[-1].read_text())
    snaps = {s["relative_path"]: s for s in data["input_snapshots"]}
    assert snaps["in.txt"]["hash_status"] == "hashed"
    assert snaps["in.txt"]["sha256"].startswith("sha256:")


def test_run_snapshots_outputs_before_and_after(tmp_path: Path, monkeypatch) -> None:
    _start(tmp_path, monkeypatch)
    (tmp_path / "results").mkdir()
    assert (
        main(
            [
                "run",
                "--outputs",
                "out.txt",
                "--",
                "python3",
                "-c",
                "open('out.txt','w').write('done')",
            ]
        )
        == 0
    )
    sidecar = json.loads(
        sorted((tmp_path / ".ro-crate-run" / "commands").glob("*.json"))[-1].read_text()
    )
    before = {s["relative_path"]: s for s in sidecar["outputs_before"]}
    after = {s["relative_path"]: s for s in sidecar["outputs_after"]}
    assert before["out.txt"]["exists"] is False
    assert after["out.txt"]["hash_status"] == "hashed"


def test_run_records_signal_failure_class(tmp_path: Path, monkeypatch) -> None:
    _start(tmp_path, monkeypatch)
    rc = main(["run", "--", "python3", "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"])
    assert rc != 0
    sidecar = json.loads(
        sorted((tmp_path / ".ro-crate-run" / "commands").glob("*.json"))[-1].read_text()
    )
    assert sidecar["signal"] == 15
    assert sidecar["failure_class"] == "signal"
