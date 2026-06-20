"""Translate Claude Code lifecycle hook events into journal events, enforce
PreToolUse policy in enforced mode, and run the Stop-hook checkpoint/validate/
block cycle. Hooks no-op when no run exists and redact before persisting."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .context import ProjectContext
from .journal import EventWriter
from .models import RcrConfig, RcrState, ValidationReport
from .redaction import Redactor, redaction_event_payload
from .state import load_config, load_state, read_events


@dataclass
class HookResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


EVENT_MAP = {
    "SessionStart": "session.started",
    "UserPromptSubmit": "human.prompt",
    "PostToolUse": "tool.completed",
    "PostToolUseFailure": "tool.failed",
    "PostToolBatch": "tool.batch.completed",
    "PermissionRequest": "permission.requested",
    "PermissionDenied": "permission.denied",
    "CwdChanged": "environment.cwd.changed",
    "FileChanged": "file.changed",
    "WorktreeCreate": "git.worktree.created",
    "WorktreeRemove": "git.worktree.removed",
    "TaskCreated": "agent.task.created",
    "TaskCompleted": "agent.task.completed",
    "SubagentStart": "agent.subagent.started",
    "SubagentStop": "agent.subagent.completed",
    "PreCompact": "conversation.compaction.started",
    "PostCompact": "conversation.compaction.completed",
    "Stop": "session.stop.requested",
    "StopFailure": "session.stop.failed",
    "SessionEnd": "session.ended",
}


def handle_hook(
    event_name: str, payload: dict[str, Any], env: dict[str, str] | None = None
) -> HookResult:
    """Dispatch a Claude Code lifecycle hook event into the run's journal.

    Ignores non-dict payloads and never crashes on an unrecognized event. When no
    run exists it no-ops (unless RCR_AUTO_START bootstraps one on a start event).
    After the shared preamble (recover state, persist session_id) it routes to a
    per-event handler from ``_HOOK_HANDLERS``; unmapped events fall through to the
    hook.unknown type. EventWriter.append redacts every payload before persistence.
    """
    # Ignore non-dict payloads and never crash on an unrecognized event.
    if not isinstance(payload, dict):
        return HookResult()
    ctx = ProjectContext.from_cwd(
        payload.get("cwd") or env.get("CLAUDE_PROJECT_DIR") if env else None, env=env
    )
    if not (ctx.state_dir / "state.json").exists():
        # Auto-start (opt-in via RCR_AUTO_START): bootstrap a run on first activity so the
        # agent's actions are captured as the workflow even without an explicit `rcr start`.
        # Only on session/prompt/tool start, never on teardown events.
        if event_name in {"SessionStart", "UserPromptSubmit", "PreToolUse"} and (env or {}).get(
            "RCR_AUTO_START"
        ):
            from .commands import auto_start_run

            if not auto_start_run(env=env):
                return HookResult()
            # A run now exists; fall through and handle this event normally.
        else:
            return HookResult()
    from .recovery import ensure_recovered

    ensure_recovered(ctx.state_dir)
    # Persist session_id from hook payload if not yet set.
    state = load_state(ctx.state_dir)
    incoming_session = payload.get("session_id") or (env or {}).get("CLAUDE_SESSION_ID")
    if incoming_session and state.session_id != incoming_session:
        state.session_id = incoming_session
        from .state import write_state

        write_state(ctx.state_dir, state)
    state = load_state(ctx.state_dir)
    writer = EventWriter(ctx.state_dir)

    handler = _HOOK_HANDLERS.get(event_name)
    if handler is not None:
        return handler(ctx, state, writer, payload)
    return _on_generic(ctx, state, writer, payload, event_name)


def _on_session_start(
    ctx: ProjectContext, state: RcrState, writer: EventWriter, payload: dict[str, Any]
) -> HookResult:
    session_id = payload.get("session_id")
    writer.append(
        "session.started",
        payload,
        source_kind="claude_hook",
        session_id=session_id,
    )
    # state.json already exists at this point (handle_hook returns early otherwise),
    # so this SessionStart is resuming an established run.
    if not _run_is_terminal(read_events(ctx.state_dir)):
        writer.append(
            "run.resumed",
            {"cwd": str(ctx.cwd), "session_id": session_id},
            source_kind="claude_hook",
            session_id=session_id,
        )
    return HookResult()


def _on_pre_tool_use(
    ctx: ProjectContext, state: RcrState, writer: EventWriter, payload: dict[str, Any]
) -> HookResult:
    redactor = _redactor_for_state(ctx.state_dir)
    cfg = load_config(ctx.state_dir)
    command = str(payload.get("tool_input", {}).get("command", ""))
    if payload.get("tool_name") == "Bash" and state.mode == "enforced":
        reason = _enforced_block_reason(command, state, cfg)
        if reason:
            writer.append(
                "tool.blocked",
                {"tool_name": "Bash", "command": command, "reason": reason},
                source_kind="claude_hook",
            )
            return HookResult(
                stdout=json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        }
                    }
                )
            )
    redacted_input = cast(dict[str, Any], redactor.redact_value(payload.get("tool_input", {}))[0])
    writer.append(
        "tool.requested",
        {
            "tool_name": payload.get("tool_name"),
            "tool_input": redacted_input,
        },
        source_kind="claude_hook",
    )
    return HookResult()


def _on_user_prompt(
    ctx: ProjectContext, state: RcrState, writer: EventWriter, payload: dict[str, Any]
) -> HookResult:
    redactor = _redactor_for_state(ctx.state_dir)
    raw_prompt = str(payload.get("prompt", ""))
    result = redactor.redact_text(raw_prompt)
    writer.append(
        "human.prompt",
        {
            "prompt_hash": hashlib.sha256(result.text.encode()).hexdigest(),
            "prompt": result.text,
        },
        source_kind="claude_hook",
        redacted=True,
    )
    if result.applied:
        writer.append(
            "redaction.applied",
            redaction_event_payload("human.prompt", result),
            source_kind="claude_hook",
            redacted=True,
        )
    return HookResult()


def _on_post_tool_use(
    ctx: ProjectContext, state: RcrState, writer: EventWriter, payload: dict[str, Any]
) -> HookResult:
    tool_name = str(payload.get("tool_name", ""))
    file_event = _file_event_for_tool(tool_name)
    if file_event:
        file_path = str(payload.get("tool_input", {}).get("file_path", ""))
        writer.append(
            file_event,
            {"path": file_path, "tool_name": tool_name},
            source_kind="claude_hook",
            inferred=True,
        )
        return HookResult()
    writer.append("tool.completed", payload, source_kind="claude_hook")
    return HookResult()


def _on_stop(
    ctx: ProjectContext, state: RcrState, writer: EventWriter, payload: dict[str, Any]
) -> HookResult:
    from .materialize.builder import checkpoint
    from .validation.validator import validate_run

    writer.append("session.stop.requested", {"mode": state.mode}, source_kind="claude_hook")
    checkpoint_rc = 0
    if _is_stale(state):
        try:
            checkpoint_rc = checkpoint(ctx.state_dir, state.requested_profile or "auto")
        except Exception as exc:
            # A corrupt journal can make checkpoint raise; block with actionable
            # guidance instead of crashing the hook.
            if state.mode == "advisory":
                return HookResult()
            return HookResult(
                exit_code=2,
                stderr=(
                    f"RO-Crate checkpoint failed: {exc}. "
                    "Run rcr status and rcr validate, then repair provenance."
                ),
            )
    if state.mode == "advisory":
        return HookResult()
    report = validate_run(ctx.state_dir, public=False, append_event=False)
    public_report = validate_run(ctx.state_dir, public=True, append_event=False)
    public_findings = [
        finding.message for finding in public_report.errors if finding.level == "privacy"
    ]
    raw_bypass = _detect_raw_bash_bypass(read_events(ctx.state_dir))
    state = load_state(ctx.state_dir)
    blockers = _stop_blockers(
        state,
        report,
        checkpoint_rc,
        mode=state.mode,
        public_findings=public_findings,
        raw_bypass=raw_bypass,
    )
    if blockers:
        reasons = "; ".join(blockers)
        return HookResult(
            exit_code=2,
            stderr=(
                f"RO-Crate provenance is not ready to stop: {reasons}. "
                "Run rcr status and rcr validate, then repair provenance."
            ),
        )
    return HookResult()


def _on_generic(
    ctx: ProjectContext,
    state: RcrState,
    writer: EventWriter,
    payload: dict[str, Any],
    event_name: str,
) -> HookResult:
    mapped = EVENT_MAP.get(event_name)
    if mapped is not None:
        writer.append(mapped, payload, source_kind="claude_hook")
    else:
        # Route unmapped lifecycle events to the hook.unknown type so the L0 vocabulary
        # check cannot fail. Preserve the original event name in the payload.
        writer.append(
            "hook.unknown", {"hook_event": event_name, **payload}, source_kind="claude_hook"
        )
    return HookResult()


HookHandler = Callable[[ProjectContext, RcrState, EventWriter, dict[str, Any]], HookResult]

# Per-event handlers. PreToolUse is registered explicitly because it is NOT in
# EVENT_MAP — it carries blocking policy beyond plain name mapping.
_HOOK_HANDLERS: dict[str, HookHandler] = {
    "SessionStart": _on_session_start,
    "PreToolUse": _on_pre_tool_use,
    "UserPromptSubmit": _on_user_prompt,
    "PostToolUse": _on_post_tool_use,
    "Stop": _on_stop,
}


def main(event_name: str) -> int:
    import os as _os

    # Re-entrancy guard: a hook-triggered subprocess that re-invokes us must no-op.
    if _os.environ.get("RCR_IN_HOOK"):
        return 0
    payload = json.loads(sys.stdin.read() or "{}")
    env = dict(_os.environ)
    env["RCR_IN_HOOK"] = "1"
    result = handle_hook(event_name, payload, env=env)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.exit_code


def _redactor_for_state(state_dir: Path) -> Redactor:
    return Redactor.for_state_dir(state_dir)


# Read-only / capture-aware command prefixes that never count as a raw substantive
# command needing `rcr run --`. python3 is handled separately because it depends on
# what the script does.
_ALLOWED_PREFIXES = (
    "pwd",
    "ls",
    "git status",
    "git rev-parse",
    "git diff",
    "cat ",
    "head ",
    "tail ",
    "rcr ",
)


def _is_substantive_raw(command: str) -> bool:
    """Return whether a Bash command is substantive work that should run via ``rcr run --``.

    A command is NOT substantive when it is empty, an allow-listed read-only/capture
    command, an `rcr`/rocrate hook invocation, or a `python3 ... rcr run` re-entry.
    Any other non-empty command counts as substantive.
    """
    stripped = command.strip()
    if not stripped:
        return False
    if stripped.startswith("python3"):
        # An rcr/rocrate-driven python3 call is part of capture, not raw work.
        return "rocrate_" not in stripped and "rcr run" not in stripped
    if any(stripped == prefix or stripped.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        return False
    return True


# ---------------------------------------------------------------------------
# Stop-hook helpers
# ---------------------------------------------------------------------------


def _is_stale(state: RcrState) -> bool:
    checkpoint = state.last_checkpoint
    if checkpoint is None:
        return True
    # The checkpoint completed event itself advances the sequence beyond
    # materialized_through_sequence; compare against the checkpoint event's
    # own sequence so that checkpoint events do not trigger a re-materialization.
    return state.sequence > checkpoint.event_sequence


def _dedupe_str(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


_REQUIRED_METADATA_CODES = {
    "missing_required_output",
    "metadata_missing",
    "metadata_invalid_json",
    "missing_software_versions",
}


def _stop_blockers(
    state: RcrState,
    report: ValidationReport,
    checkpoint_rc: int,
    *,
    mode: str,
    public_findings: list[str] | None = None,
    raw_bypass: list[str] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if checkpoint_rc != 0:
        blockers.append("crate materialization failed")
    for finding in report.errors:
        # Critical structural failures (corrupt journal, bad state, invalid JSON-LD /
        # RO-Crate) block in monitored mode too; profile/reproducibility quality errors
        # block only in enforced (via report.status below).
        if (
            finding.level in {"journal", "state", "ro_crate"}
            or finding.code in _REQUIRED_METADATA_CODES
        ):
            blockers.append(finding.message)
    blockers.extend(public_findings or [])
    if mode == "enforced":
        if report.status == "failed":
            blockers.append("crate validation failed")
        if state.current_phase_id:
            blockers.append(f"open phase {state.current_phase_id}")
        if state.current_step_id:
            blockers.append(f"open step {state.current_step_id}")
        blockers.extend(raw_bypass or [])
    return _dedupe_str(blockers)


def _run_is_terminal(events: list[dict[str, Any]]) -> bool:
    return any(
        event.get("event_type") in {"run.finalized", "run.aborted"} for event in events
    )


def _detect_raw_bash_bypass(events: list[dict[str, Any]]) -> list[str]:
    bypass: list[str] = []
    for event in events:
        if event.get("event_type") not in {"tool.completed", "tool.requested"}:
            continue
        payload = event.get("payload", {})
        if payload.get("tool_name") != "Bash":
            continue
        command = str(payload.get("tool_input", {}).get("command", ""))
        if _is_substantive_raw(command):
            summary = command.strip().splitlines()[0][:80] if command.strip() else "command"
            bypass.append(f"raw substantive command bypassed capture: {summary}")
    return _dedupe_str(bypass)


# ---------------------------------------------------------------------------
# PreToolUse enforcement helpers
# ---------------------------------------------------------------------------

_OUTPUT_WRITE_TOKENS = (">", ">>", "| tee", "|tee", "tee ")
_OUTPUT_WRITE_COMMANDS = ("cp ", "mv ", "dd ", "rsync ")

_EXFIL_PATTERNS = (
    re.compile(r"\bcurl\b[^\n|]*\|\s*(ba)?sh\b"),
    re.compile(r"\bwget\b[^\n|]*\|\s*(ba)?sh\b"),
    re.compile(r"\b(curl|wget)\b[^\n]*\b(\.env|id_rsa|id_ed25519|credentials|\.aws/)\b"),
    re.compile(r"\b(cat|base64)\b[^\n]*(\.env|id_rsa|credentials)[^\n]*\|\s*(curl|wget|nc)\b"),
    re.compile(r"\bnc\b\s+-?\w*\s*\S+\s+\d+"),
    re.compile(r"\bscp\b[^\n]*@[^\n]*:"),
)

_DESTRUCTIVE_PREFIXES = ("rm ", "rm\t", "shred ", "truncate ", "git clean")
_EVIDENCE_PATHS = (".ro-crate-run",)


def _writes_into_output_roots(command: str, cfg: RcrConfig) -> bool:
    roots = list(cfg.output_roots)
    if not roots:
        return False
    mentions_root = any(
        f"{root}/" in command or command.strip().endswith(root) for root in roots
    )
    if not mentions_root:
        return False
    return any(token in command for token in _OUTPUT_WRITE_TOKENS) or command.strip().startswith(
        _OUTPUT_WRITE_COMMANDS
    )


def _is_destructive_to_evidence(command: str, state: RcrState, cfg: RcrConfig) -> bool:
    stripped = command.strip()
    if not stripped.startswith(_DESTRUCTIVE_PREFIXES):
        return False
    protected = set(_EVIDENCE_PATHS) | set(cfg.output_roots)
    for declared in state.declared_outputs:
        path = str(declared.get("path", ""))
        if path:
            protected.add(path)
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        tokens = stripped.split()
    return any(
        any(
            token == target or token.startswith(f"{target}/") or target in token
            for token in tokens
        )
        for target in protected
    )


def _is_exfiltration(command: str) -> bool:
    return any(pattern.search(command) for pattern in _EXFIL_PATTERNS)


def _enforced_block_reason(command: str, state: RcrState, cfg: RcrConfig) -> str | None:
    """Return the reason an enforced-mode Bash command is blocked, or None to allow it.

    The specific guards (output-root writes, evidence deletion, exfiltration) are
    checked before the general substantive-command catch-all so the more actionable
    message wins when more than one condition holds.
    """
    # Blocks commands that write into a declared output root; checked first so the
    # more specific message wins.
    if _writes_into_output_roots(command, cfg):
        return "Commands writing into declared output roots must run via rcr run --"
    # Blocks commands that delete provenance evidence; checked before the general
    # substantive test so the evidence-protection message wins.
    if _is_destructive_to_evidence(command, state, cfg):
        return "Destructive commands that delete provenance evidence are blocked in enforced mode"
    # Blocks secret-exfiltration / unsafe network patterns.
    if _is_exfiltration(command):
        return "Command matches a secret-exfiltration / unsafe pattern and is blocked"
    # Blocks raw substantive Bash; the catch-all, checked last.
    if _is_substantive_raw(command):
        return "Substantive commands must use rcr run -- in enforced mode"
    return None


# ---------------------------------------------------------------------------
# PostToolUse helpers
# ---------------------------------------------------------------------------


def _file_event_for_tool(tool_name: str) -> str | None:
    return {
        "Write": "file.created",
        "Edit": "file.modified",
        "MultiEdit": "file.modified",
        "NotebookEdit": "file.modified",
    }.get(tool_name)
