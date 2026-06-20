"""Execute a user command under provenance capture: snapshot inputs/outputs,
stream and redact stdout/stderr, write a sidecar record, and journal the
execution.command.started / completed / failed events."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .files import file_record
from .git import observe_git_state
from .ids import IdMap
from .journal import EventWriter
from .redaction import Redactor
from .state import load_config, load_state
from .time import utc_now


class CommandRunner:
    def __init__(self, state_dir: Path, project_dir: Path | None = None) -> None:
        self.state_dir = state_dir
        self.project_dir = project_dir or state_dir.parent

    def _snapshot(
        self, outputs: list[str], output_roots: list[str], max_hash_bytes: int
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        seen: set[str] = set()
        for rel in outputs:
            target = self.project_dir / rel
            records.append(file_record(target, self.project_dir, max_hash_bytes))
            seen.add(str(target))
        for root in output_roots:
            root_dir = self.project_dir / root
            if root_dir.exists():
                for path in sorted(root_dir.rglob("*")):
                    if path.is_file() and str(path) not in seen:
                        records.append(file_record(path, self.project_dir, max_hash_bytes))
                        seen.add(str(path))
        return records

    def run(
        self,
        argv: list[str],
        *,
        step: str | None = None,
        inputs: list[str] | None = None,
        outputs: list[str] | None = None,
    ) -> int:
        if not argv:
            raise ValueError("rcr run requires a command after --")
        state = load_state(self.state_dir)
        command_id = f"cmd_{state.sequence + 1:06d}"
        id_map = IdMap(self.state_dir)
        action_id = id_map.entity_for_event(command_id)
        inputs = inputs or []
        outputs = outputs or []
        cfg = load_config(self.state_dir)
        redactor = Redactor.for_state_dir(self.state_dir)
        argv_results = [redactor.redact_text(arg) for arg in argv]
        recorded_argv = [r.text for r in argv_results]
        argv_applied = sum(r.applied for r in argv_results)
        recorded_display = redactor.redact_text(shlex.join(argv)).text
        env_capture = redactor.capture_environment(dict(os.environ))
        max_hash_bytes = cfg.hash_policy.max_file_size_mb * 1024 * 1024
        input_snapshots = [
            file_record(
                self.project_dir / inp,
                self.project_dir,
                max_hash_bytes,
            )
            for inp in inputs
        ]
        outputs_before = self._snapshot(outputs, cfg.output_roots, max_hash_bytes)
        sidecar_rel = f".ro-crate-run/commands/{command_id}.json"
        stdout_rel = f".ro-crate-run/logs/{command_id}.stdout.txt"
        stderr_rel = f".ro-crate-run/logs/{command_id}.stderr.txt"
        sidecar_path = self.project_dir / sidecar_rel
        stdout_path = self.project_dir / stdout_rel
        stderr_path = self.project_dir / stderr_rel
        started_at = utc_now()
        writer = EventWriter(self.state_dir)
        started_event = writer.append(
            "execution.command.started",
            {
                "command_id": command_id,
                "action_id": action_id,
                "argv": recorded_argv,
                "cwd": str(self.project_dir),
                "display_command": recorded_display,
                "sidecar": sidecar_rel,
                "stdout_log": stdout_rel,
                "stderr_log": stderr_rel,
                "inputs": inputs,
                "outputs": outputs,
            },
            source_kind="human_cli",
            step_id=step,
        )
        sidecar = {
            "schema_version": "1.0.0",
            "command_id": command_id,
            "action_id": action_id,
            "started_event_id": started_event.event_id,
            "argv": recorded_argv,
            "shell": False,
            "cwd": str(self.project_dir),
            "project_root": str(self.project_dir),
            "display_command": recorded_display,
            "started_at": started_at,
            "inputs": inputs,
            "outputs": outputs,
            "input_snapshots": input_snapshots,
            "outputs_before": outputs_before,
            "environment": env_capture,
            "git_before": observe_git_state(self.project_dir),
        }
        sidecar_redactions = _write_sidecar(sidecar_path, sidecar, redactor)
        start = time.monotonic()
        stream_counts: dict[str, int] = {"stdout": 0, "stderr": 0}
        pump_errors: dict[str, str] = {}

        def _pump(name: str, pipe: Any, path: Path) -> None:
            # Runs in a thread; an unhandled exception here would die silently at join(),
            # leaving the command journaled as completed with truncated logs. Capture any
            # write/IO failure so it is recorded on the command record instead.
            applied = 0
            try:
                with path.open("w", encoding="utf-8") as handle:
                    for line in iter(pipe.readline, ""):
                        redacted = redactor.redact_text(line)
                        handle.write(redacted.text)
                        applied += redacted.applied
            except OSError as exc:
                pump_errors[name] = f"{type(exc).__name__}: {exc}"
            finally:
                stream_counts[name] = applied
                try:
                    pipe.close()
                except OSError:
                    pass

        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(self.project_dir),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
        except OSError as exc:
            ended_at = utc_now()
            duration = time.monotonic() - start
            stdout_path.write_text("", encoding="utf-8")
            stderr_result = redactor.redact_text(f"{type(exc).__name__}: {exc}\n")
            stderr_path.write_text(stderr_result.text, encoding="utf-8")
            outputs_after = self._snapshot(outputs, cfg.output_roots, max_hash_bytes)
            sidecar.update(
                {
                    "ended_at": ended_at,
                    "duration_seconds": duration,
                    "exit_code": 127,
                    "signal": None,
                    "failure_class": "startup_error",
                    "terminal_status": "failed",
                    "error": stderr_result.text.strip(),
                    "git_after": observe_git_state(self.project_dir),
                    "outputs_after": outputs_after,
                    "output_snapshots": outputs_after,
                }
            )
            sidecar_redactions += _write_sidecar(sidecar_path, sidecar, redactor)
            writer.append(
                "execution.command.failed",
                {
                    "command_id": command_id,
                    "action_id": action_id,
                    "started_event_id": started_event.event_id,
                    "argv": recorded_argv,
                    "cwd": str(self.project_dir),
                    "display_command": recorded_display,
                    "exit_code": 127,
                    "ended_at": ended_at,
                    "duration_seconds": duration,
                    "failure_class": "startup_error",
                    "error": stderr_result.text.strip(),
                    "sidecar": sidecar_rel,
                    "stdout_log": stdout_rel,
                    "stderr_log": stderr_rel,
                    "inputs": inputs,
                    "outputs": outputs,
                },
                source_kind="human_cli",
                step_id=step,
            )
            total_applied = argv_applied + stderr_result.applied + sidecar_redactions
            if total_applied:
                writer.append(
                    "redaction.applied",
                    {"context": "execution.command", "applied": total_applied, "categories": []},
                    source_kind="human_cli",
                    redacted=True,
                )
            return 127
        threads = [
            threading.Thread(target=_pump, args=("stdout", proc.stdout, stdout_path)),
            threading.Thread(target=_pump, args=("stderr", proc.stderr, stderr_path)),
        ]
        for thread in threads:
            thread.start()
        returncode = proc.wait()
        for thread in threads:
            thread.join()
        duration = time.monotonic() - start
        ended_at = utc_now()
        signal_num: int | None = -returncode if returncode < 0 else None
        failure_class: str | None = (
            None
            if returncode == 0
            else "signal"
            if signal_num is not None
            else "nonzero_exit"
        )
        outputs_after = self._snapshot(outputs, cfg.output_roots, max_hash_bytes)
        sidecar.update(
            {
                "ended_at": ended_at,
                "duration_seconds": duration,
                "exit_code": returncode,
                "signal": signal_num,
                "failure_class": failure_class,
                "git_after": observe_git_state(self.project_dir),
                "outputs_after": outputs_after,
                "output_snapshots": outputs_after,
            }
        )
        if pump_errors:
            sidecar["log_write_errors"] = pump_errors
        sidecar_redactions += _write_sidecar(sidecar_path, sidecar, redactor)
        payload = {
            "command_id": command_id,
            "action_id": action_id,
            "started_event_id": started_event.event_id,
            "argv": recorded_argv,
            "cwd": str(self.project_dir),
            "display_command": recorded_display,
            "exit_code": returncode,
            "ended_at": ended_at,
            "duration_seconds": duration,
            "sidecar": sidecar_rel,
            "stdout_log": stdout_rel,
            "stderr_log": stderr_rel,
            "inputs": inputs,
            "outputs": outputs,
        }
        if pump_errors:
            # Surface truncated/incomplete logs on the command record (not silently lost).
            payload["log_write_errors"] = pump_errors
        failure_payload: dict[str, Any] = {}
        if returncode != 0:
            failure_payload["failure_class"] = failure_class or "nonzero_exit"
            if signal_num is not None:
                failure_payload["signal"] = signal_num
        writer.append(
            "execution.command.completed" if returncode == 0 else "execution.command.failed",
            payload | failure_payload,
            source_kind="human_cli",
            step_id=step,
        )
        total_applied = (
            stream_counts["stdout"]
            + stream_counts["stderr"]
            + argv_applied
            + sidecar_redactions
        )
        if total_applied:
            writer.append(
                "redaction.applied",
                {"context": "execution.command", "applied": total_applied, "categories": []},
                source_kind="human_cli",
                redacted=True,
            )
        return returncode


def _write_sidecar(path: Path, payload: dict[str, Any], redactor: Redactor) -> int:
    redacted, applied = redactor.redact_value(payload)
    path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n")
    return applied
