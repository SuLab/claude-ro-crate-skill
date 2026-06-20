"""Command handlers behind the ``rcr`` CLI: start/resume runs, declare
inputs/outputs/parameters/software, run captured commands, checkpoint, validate,
finalize, sign/verify, redact, install the project, and import an RO-Crate."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from . import __version__
from .config import default_config
from .constants import CONTAINER_MANIFESTS, DEPENDENCY_MANIFESTS
from .context import ProjectContext
from .export import finalize
from .files import sha256_file
from .git import observe_git_state
from .journal import EventWriter
from .materialize.builder import checkpoint
from .models import RcrState
from .recovery import ensure_recovered, is_active_run, recover_state
from .redact import redact_run
from .redaction import Redactor, redaction_event_payload
from .runner import CommandRunner
from .signing import (
    generate_keypair,
    public_key_from_private,
    sign_manifest,
    signing_available,
    verify_manifest_signature,
)
from .state import (
    detect_output_changes,
    ensure_runtime_dirs,
    initial_state,
    load_config,
    load_state,
    read_events,
    update_state,
    write_config,
    write_id_map,
    write_state,
)
from .validation.validator import validate_run


def _bootstrap_run(
    ctx: ProjectContext, title: str, mode: str, profile: str,
    *, source_kind: str = "skill_command",
) -> Path:
    """Create the .ro-crate-run state + emit run.started / environment.observed.

    Shared by `rcr start` and hook auto-start so the agent's actions are captured
    from the very first event, even when no human ran `rcr start`.
    """
    state_dir = ctx.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_dirs(state_dir)
    cfg = default_config(project_name=ctx.project_dir.name, mode=mode, profile=profile)
    state = initial_state(title, cfg)
    state.requested_profile = profile
    state.session_id = os.environ.get("CLAUDE_SESSION_ID")
    write_config(state_dir, cfg)
    write_state(state_dir, state)
    write_id_map(state_dir)
    policy_path = state_dir / "secrets-redaction.json"
    if not policy_path.exists():
        policy_path.write_text(
            json.dumps(
                {
                    "_comment": "Add project-specific secret regexes here; merged with built-ins.",
                    "patterns": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    writer = EventWriter(state_dir)
    # Record Claude Code session metadata (present-only; absent keys are omitted, not null).
    claude_meta: dict[str, str] = {}
    for env_key, field_name in (
        ("CLAUDE_SESSION_ID", "session_id"),
        ("CLAUDE_CODE_VERSION", "version"),
        ("CLAUDE_VERSION", "version"),
        ("CLAUDE_MODEL", "model"),
        ("CLAUDE_MODEL_ID", "model"),
    ):
        value = os.environ.get(env_key)
        if value:
            claude_meta.setdefault(field_name, value)
    run_started_payload: dict[str, Any] = {
        "title": title,
        "cwd": str(ctx.cwd),
        "project_root": str(ctx.project_dir),
        "mode": mode,
        "profile": profile,
    }
    if claude_meta:
        run_started_payload["claude"] = claude_meta
    writer.append("run.started", run_started_payload, source_kind=source_kind)
    writer.append(
        "environment.observed",
        {
            "cwd": str(ctx.cwd),
            "project_root": str(ctx.project_dir),
            "git": observe_git_state(ctx.project_dir),
            "python": sys.version.split()[0],
            "cli_version": __version__,
            "skill_version": __version__,
            "rocrate_package_version": _package_version("rocrate"),
            "os": platform.platform(),
            "privacy": cfg.privacy.__dict__,
        },
        source_kind=source_kind,
    )
    return state_dir


def _archive_closed_run(state_dir: Path) -> str:
    """Relocate a closed run's journal/state so a fresh `rcr start` gets a clean chain.

    A terminal run's events.ndjson must never receive a freshly-bootstrapped sequence-1
    event appended onto it — EventWriter.append always opens the file in append mode and
    derives sequence/previous_event_hash from the just-reset state, which produces a
    non-monotonic sequence and a broken hash chain. So the prior run's core files are moved
    into `.ro-crate-run/archive/<run_id>/` (inert: file inclusion ignores `.ro-crate-run/**`)
    before bootstrapping. Returns the archived run_id (best-effort).
    """
    try:
        run_id = load_state(state_dir).run_id
    except Exception:
        run_id = "closed-run"
    dest = state_dir / "archive" / run_id
    base = dest
    n = 1
    while dest.exists():
        n += 1
        dest = base.parent / f"{base.name}.{n}"
    dest.mkdir(parents=True, exist_ok=True)
    # Move the chain/state files AND the derived crate output so the new run starts truly
    # fresh (no stale crate that `rcr validate` would mistake for the new run's output).
    for name in ("events.ndjson", "state.json", "id-map.json", "ro-crate"):
        src = state_dir / name
        if src.exists():
            shutil.move(str(src), str(dest / name))
    return run_id


def start(title: str, mode: str, profile: str, no_checkpoint: bool = False) -> int:
    """Begin a run: bootstrap state + emit run.started, or reconcile an existing run.

    An active run is left untouched (idempotent); a closed run is archived first.
    """
    ctx = ProjectContext.from_cwd()
    # A second `rcr start` MUST NOT clobber an existing run's state with a fresh
    # initial_state — that orphans the journal (new run_id + reset sequence) and breaks the
    # hash chain (non-monotonic sequence, previous-hash mismatch). Two cases when state.json
    # already exists:
    if (ctx.state_dir / "state.json").exists():
        if is_active_run(read_events(ctx.state_dir)):
            # (a) Run still active: idempotent. Reconcile from the authoritative journal and
            #     checkpoint the EXISTING run. Pass "auto" — NOT the new --profile — so a
            #     duplicate start can't silently re-target the run's profile (which would
            #     flip validation). All args of the duplicate start are effectively ignored.
            ensure_recovered(ctx.state_dir)
            existing = load_state(ctx.state_dir)
            print(
                f"A run is already active ({existing.run_id}); ignoring duplicate 'rcr start'. "
                "Use 'rcr resume' to continue or 'rcr abort' to end it first.",
                file=sys.stderr,
            )
            if not no_checkpoint:
                return checkpoint(ctx.state_dir, requested_profile="auto")
            return 0
        # (b) Prior run is closed (finalized/aborted). Archive it so the new run starts on a
        #     clean hash chain instead of appending a fresh sequence onto the old journal.
        archived = _archive_closed_run(ctx.state_dir)
        print(
            f"Previous run ({archived}) is closed; archived it under "
            ".ro-crate-run/archive/ and starting a new run.",
            file=sys.stderr,
        )
    state_dir = _bootstrap_run(ctx, title, mode, profile)
    if not no_checkpoint:
        return checkpoint(state_dir, requested_profile=profile)
    return 0


def auto_start_run(env: dict[str, str] | None = None) -> bool:
    """Bootstrap a run from a hook when none exists yet (opt-in via RCR_AUTO_START).

    Returns True if a run was created. Lets the agent's actions be captured as the
    workflow from session start even when no human ran `rcr start`.
    """
    ctx = ProjectContext.from_cwd(env=env)
    if (ctx.state_dir / "state.json").exists():
        return False
    title = ctx.project_dir.name or "Claude Code session"
    _bootstrap_run(ctx, title, mode="advisory", profile="auto", source_kind="claude_hook")
    return True


def resume() -> int:
    ctx = ProjectContext.from_cwd()
    recover_state(ctx.state_dir, active_run=True)
    EventWriter(ctx.state_dir).append(
        "run.resumed", {"cwd": str(ctx.cwd)}, source_kind="skill_command"
    )
    _refresh_run_dirty(ctx.state_dir)
    _print_status(ctx.state_dir, json_output=False)
    return 0


def status(json_output: bool = False) -> int:
    ctx = ProjectContext.from_cwd()
    from .recovery import ensure_recovered

    ensure_recovered(ctx.state_dir)
    # Surface side-effect dirtiness (materializer version / output-hash change).
    _refresh_run_dirty(ctx.state_dir)
    _print_status(ctx.state_dir, json_output=json_output)
    return 0


def _print_status(state_dir: Path, *, json_output: bool = False) -> None:
    state = load_state(state_dir)
    validation = validate_run(state_dir, strict=False, public=False, append_event=False)
    missing_required_metadata = []
    if not state.known_software:
        missing_required_metadata.append("software")
    payload = {
        "run_id": state.run_id,
        "mode": state.mode,
        "selected_profile": state.selected_profile,
        "current_phase_id": state.current_phase_id,
        "current_step_id": state.current_step_id,
        "event_count": state.sequence,
        "last_checkpoint": state.last_checkpoint.__dict__ if state.last_checkpoint else None,
        "dirty": state.dirty,
        "declared_inputs": state.declared_inputs,
        "declared_outputs": state.declared_outputs,
        "missing_required_metadata": missing_required_metadata,
        "privacy_warnings": [
            warning.message for warning in validation.warnings if warning.level == "privacy"
        ],
        "validation": {
            "status": validation.status,
            "levels": validation.levels,
            "errors": [error.__dict__ for error in validation.errors],
            "warnings": [warning.__dict__ for warning in validation.warnings],
        },
        "warnings": state.warnings,
        "errors": state.errors,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        dirty_flag = " [STALE]" if state.dirty else ""
        lines = [
            f"Run: {state.run_id}",
            f"Mode: {state.mode}",
            f"Profile: {state.selected_profile}",
            f"Phase: {state.current_phase_id or '-'}",
            f"Step: {state.current_step_id or '-'}",
            f"Events: {state.sequence}",
            f"Last checkpoint: {state.last_checkpoint.timestamp if state.last_checkpoint else '-'}{dirty_flag}",
            f"Validation: {validation.status}",
        ]
        if state.declared_inputs:
            lines.append(f"Declared inputs ({len(state.declared_inputs)}):")
            for inp in state.declared_inputs:
                lines.append(f"  {inp.get('path', '?')} [{inp.get('existence', '?')}]")
        if state.declared_outputs:
            lines.append(f"Declared outputs ({len(state.declared_outputs)}):")
            for out in state.declared_outputs:
                lines.append(f"  {out.get('path', '?')} [{out.get('existence', '?')}]")
        if missing_required_metadata:
            lines.append(f"Missing required metadata: {', '.join(missing_required_metadata)}")
        privacy_warns = cast(list[str], payload.get("privacy_warnings") or [])
        if privacy_warns:
            lines.append("Privacy warnings:")
            for pw in privacy_warns:
                lines.append(f"  {pw}")
        print("\n".join(lines))


def note(text: str, public: bool = False) -> int:
    ctx = ProjectContext.from_cwd()
    result = Redactor.for_state_dir(ctx.state_dir).redact_text(text)
    writer = EventWriter(ctx.state_dir)
    writer.append(
        "human.note",
        {"text": result.text},
        visibility="public" if public else "private",
        source_kind="human_cli",
        redacted=result.applied > 0,
    )
    if result.applied:
        writer.append(
            "redaction.applied",
            redaction_event_payload("human.note", result),
            source_kind="human_cli",
            redacted=True,
        )
    return 0


def decision(text: str, rationale: str | None = None, public: bool = False) -> int:
    ctx = ProjectContext.from_cwd()
    redactor = Redactor.for_state_dir(ctx.state_dir)
    text_result = redactor.redact_text(text)
    payload: dict[str, Any] = {"text": text_result.text}
    results = [text_result]
    if rationale:
        rationale_result = redactor.redact_text(rationale)
        payload["rationale"] = rationale_result.text
        results.append(rationale_result)
    redacted_flag = any(result.applied for result in results)
    writer = EventWriter(ctx.state_dir)
    writer.append(
        "human.decision",
        payload,
        visibility="public" if public else "private",
        source_kind="human_cli",
        redacted=bool(redacted_flag),
    )
    if redacted_flag:
        writer.append(
            "redaction.applied",
            redaction_event_payload("human.decision", *results),
            source_kind="human_cli",
            redacted=True,
        )
    return 0


def declare_io(
    kind: str,
    path: str,
    role: str | None,
    description: str | None,
    required: bool,
    copy: bool | None,
    visibility: str = "private",
    existence: str | None = None,
) -> int:
    ctx = ProjectContext.from_cwd()
    existence_val = existence or _classify_existence(path, kind, required)
    payload: dict[str, Any] = {
        "path": path,
        "existence": existence_val,
        "required": required,
        "copy_policy": "copy" if copy else "reference",
    }
    # Hash local input files (sha256 + size) so the missing_input_hash warning is suppressible.
    if kind == "input" and existence_val.startswith("observed"):
        local_path = Path(path)
        cfg = load_config(ctx.state_dir)
        max_bytes = cfg.hash_policy.max_file_size_mb * 1024 * 1024
        if local_path.exists() and local_path.is_file():
            if local_path.stat().st_size <= max_bytes:
                input_digest = sha256_file(local_path)
                if input_digest:
                    payload["sha256"] = input_digest.replace("sha256:", "")
                    payload["size"] = local_path.stat().st_size
    if role:
        payload["role"] = role
    if description:
        payload["description"] = description
    event_type = "workflow.input.declared" if kind == "input" else "workflow.output.declared"
    EventWriter(ctx.state_dir).append(
        event_type,
        payload,
        source_kind="human_cli",
        declared=True,
        observed=False,
        visibility=visibility,
    )
    from .state import record_known_output

    def _apply(s: RcrState) -> None:
        if kind == "input":
            s.declared_inputs.append(payload)
        else:
            s.declared_outputs.append(payload)
            actual = Path(path)
            digest = sha256_file(actual) if (actual.exists() and actual.is_file()) else None
            record_known_output(s, path, digest)

    update_state(ctx.state_dir, _apply)
    return 0


def _refresh_run_dirty(state_dir: Path) -> None:
    """Set state.dirty for side-effect triggers not captured by events: a changed
    materializer version since the last checkpoint, or changed on-disk output hashes."""
    state = load_state(state_dir)
    if state.dirty:
        return
    cfg = load_config(state_dir)
    max_bytes = cfg.hash_policy.max_file_size_mb * 1024 * 1024
    chk = state.last_checkpoint
    version_changed = bool(chk and chk.materializer_version not in {None, __version__})
    if version_changed or detect_output_changes(state_dir, state, max_bytes):
        update_state(state_dir, lambda s: setattr(s, "dirty", True))


def _classify_existence(path: str, kind: str, required: bool) -> str:
    if "://" in path:
        return "observed remote"
    if Path(path).exists():
        return "observed local"
    if kind == "output":
        return "expected" if required else "declared-only"
    return "missing" if required else "declared-only"


def parameter(
    name: str,
    value: str,
    formal_parameter: str | None,
    value_type: str | None,
    *,
    connect_from: str | None = None,
    connect_to: str | None = None,
) -> int:
    ctx = ProjectContext.from_cwd()
    payload: dict[str, object] = {"name": name, "value": value}
    if formal_parameter:
        payload["formal_parameter"] = formal_parameter
    if value_type:
        payload["type"] = value_type
    if connect_from and connect_to:
        # ParameterConnection: links an upstream output parameter to a downstream input.
        payload["connection"] = {"source": connect_from, "target": connect_to}
    EventWriter(ctx.state_dir).append(
        "workflow.parameter.declared",
        payload,
        source_kind="human_cli",
        declared=True,
        observed=False,
    )
    return 0


def _parse_image_ref(ref: str) -> tuple[str, str, str, str]:
    """Split an OCI image reference into (registry, image, tag, digest)."""
    registry = ""
    digest = ""
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    if "/" in ref:
        first, rest = ref.split("/", 1)
        # A leading segment with a dot, a port, or "localhost" is a registry host.
        if "." in first or ":" in first or first == "localhost":
            registry, ref = first, rest
    tag = ""
    if ":" in ref:
        ref, tag = ref.rsplit(":", 1)
    return registry, ref, tag, digest


def container(ref: str, digest: str | None = None) -> int:
    ctx = ProjectContext.from_cwd()
    registry, image, tag, ref_digest = _parse_image_ref(ref)
    payload = {
        "registry": registry,
        "image": image,
        "tag": tag,
        "digest": digest or ref_digest,
    }
    EventWriter(ctx.state_dir).append(
        "container.observed",
        payload,
        source_kind="human_cli",
        declared=True,
        observed=False,
    )
    return 0


def software(command_or_name: str, version: str | None, software_type: str | None) -> int:
    ctx = ProjectContext.from_cwd()
    probed_version, executable_path = _probe_software(command_or_name)
    payload = {
        "name": command_or_name,
        "command": command_or_name,
        "version": version or probed_version or "unknown",
        "type": software_type or "SoftwareApplication",
    }
    if executable_path:
        payload["executable_path"] = executable_path
    EventWriter(ctx.state_dir).append("software.observed", payload, source_kind="human_cli")
    update_state(ctx.state_dir, lambda s: s.known_software.append(payload))
    _scan_lockfiles(ctx)
    return 0


def _scan_lockfiles(ctx: ProjectContext) -> None:
    writer = EventWriter(ctx.state_dir)
    # Dependency/environment manifests matched by exact filename (lockfiles, package
    # manifests, workflow definitions, container files); Dockerfile/Containerfile are
    # recorded as kind="container", the rest as kind="lockfile".
    for name in (*DEPENDENCY_MANIFESTS, "Dockerfile", "Containerfile"):
        candidate = ctx.project_dir / name
        if candidate.exists() and candidate.is_file():
            kind = "container" if name in CONTAINER_MANIFESTS else "lockfile"
            writer.append(
                "dependency.lockfile.observed",
                {
                    "path": name,
                    "kind": kind,
                    "file_record": sha256_file(candidate),
                },
                source_kind="human_cli",
            )
    # CWL/WDL workflow definition files (scanned for *.cwl, *.wdl).
    for pattern, wf_kind in (("*.cwl", "cwl-workflow"), ("*.wdl", "wdl-workflow")):
        for candidate in ctx.project_dir.glob(pattern):
            if candidate.is_file():
                writer.append(
                    "dependency.lockfile.observed",
                    {
                        "path": str(candidate.relative_to(ctx.project_dir)),
                        "kind": wf_kind,
                        "file_record": sha256_file(candidate),
                    },
                    source_kind="human_cli",
                )


def phase(args: list[str]) -> int:
    ctx = ProjectContext.from_cwd()
    writer = EventWriter(ctx.state_dir)
    state = load_state(ctx.state_dir)
    new_phase: str | None
    if args and args[0] == "complete":
        name = args[1] if len(args) > 1 else state.current_phase_id or "phase"
        writer.append(
            "workflow.phase.completed", {"name": name}, source_kind="human_cli", phase_id=name
        )
        new_phase = None
    else:
        name = args[0]
        if "--complete-current" in args and state.current_phase_id:
            writer.append(
                "workflow.phase.completed",
                {"name": state.current_phase_id},
                source_kind="human_cli",
            )
        writer.append(
            "workflow.phase.started", {"name": name}, source_kind="human_cli", phase_id=name
        )
        new_phase = name
    update_state(ctx.state_dir, lambda s: setattr(s, "current_phase_id", new_phase))
    return 0


def step(
    action: str,
    step_id: str,
    workflow_step: str | None = None,
    description: str | None = None,
    status_value: str = "completed",
) -> int:
    ctx = ProjectContext.from_cwd()
    writer = EventWriter(ctx.state_dir)
    if action == "start":
        payload = {"step_id": step_id, "workflow_step": workflow_step or step_id}
        if description:
            payload["description"] = description
        writer.append("workflow.step.started", payload, source_kind="human_cli", step_id=step_id)
        update_state(ctx.state_dir, lambda s: setattr(s, "current_step_id", step_id))
    else:
        payload = {"step_id": step_id, "status": status_value}
        event_type = {
            "failed": "workflow.step.failed",
            "skipped": "workflow.step.skipped",
        }.get(status_value, "workflow.step.completed")
        writer.append(event_type, payload, source_kind="human_cli", step_id=step_id)

        def _clear(s: RcrState) -> None:
            if s.current_step_id == step_id:
                s.current_step_id = None

        update_state(ctx.state_dir, _clear)
    return 0


def run_command(argv: list[str], step_id: str | None, inputs: list[str], outputs: list[str]) -> int:
    ctx = ProjectContext.from_cwd()
    return CommandRunner(ctx.state_dir, ctx.project_dir).run(
        argv, step=step_id, inputs=inputs, outputs=outputs
    )


def do_checkpoint(profile: str = "auto") -> int:
    ctx = ProjectContext.from_cwd()
    return checkpoint(ctx.state_dir, requested_profile=profile)


def do_validate(strict: bool = False, json_output: bool = False, public: bool = False) -> int:
    """Validate the current run and print the report; ``public`` runs the L5 export gate."""
    ctx = ProjectContext.from_cwd()
    report = validate_run(ctx.state_dir, strict=strict, public=public)
    if json_output:
        print(json.dumps(report.__dict__, default=lambda o: o.__dict__, indent=2, sort_keys=True))
    else:
        print(
            f"RO-Crate validation: {report.status}\nProfile: {report.profile}\nErrors: {len(report.errors)}\nWarnings: {len(report.warnings)}"
        )
    return 0 if report.status != "failed" else 1


def do_sign() -> int:
    """Sign the crate manifest with an Ed25519 key stored under .ro-crate-run/keys/."""
    ctx = ProjectContext.from_cwd()
    if not signing_available():
        print("Signing unavailable: install 'ro-crate-run[signing]'.", file=sys.stderr)
        return 1
    crate = ctx.state_dir / "ro-crate"
    manifest = crate / "ro-crate-metadata.json"
    if not manifest.exists():
        print("No crate to sign; run rcr checkpoint first.", file=sys.stderr)
        return 1
    keys_dir = ctx.state_dir / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    private_path = keys_dir / "private.pem"
    public_path = keys_dir / "public.pem"
    if private_path.exists():
        private_pem = private_path.read_text()
        # Recreate public.pem from the private key if it went missing, so `rcr verify`
        # (which needs the public key) keeps working.
        if not public_path.exists():
            public_path.write_text(public_key_from_private(private_pem))
    else:
        private_pem, public_pem = generate_keypair()
        private_path.write_text(private_pem)
        public_path.write_text(public_pem)
    signature = sign_manifest(manifest, private_pem)
    (crate / "ro-crate-metadata.json.sig").write_text(signature + "\n")
    EventWriter(ctx.state_dir).append(
        "crate.signed",
        {"algorithm": "ed25519", "signature_file": "ro-crate-metadata.json.sig"},
        source_kind="skill_command",
    )
    print("Crate manifest signed (ed25519).")
    return 0


def do_verify() -> int:
    """Verify the crate manifest signature against the recorded ed25519 public key."""
    ctx = ProjectContext.from_cwd()
    if not signing_available():
        print("Signing unavailable: install 'ro-crate-run[signing]'.", file=sys.stderr)
        return 1
    crate = ctx.state_dir / "ro-crate"
    manifest = crate / "ro-crate-metadata.json"
    sig_path = crate / "ro-crate-metadata.json.sig"
    public_path = ctx.state_dir / "keys" / "public.pem"
    for p, what in (
        (manifest, "crate manifest"),
        (sig_path, "signature file"),
        (public_path, "public key"),
    ):
        if not p.exists():
            print(f"Cannot verify: {what} not found ({p.name}); run rcr sign first.",
                  file=sys.stderr)
            return 1
    ok = verify_manifest_signature(
        manifest, sig_path.read_text().strip(), public_path.read_text()
    )
    if not ok:
        print("Signature INVALID: the manifest does not match the recorded signature.",
              file=sys.stderr)
        return 1
    print("Signature OK: crate manifest verifies against the recorded ed25519 public key.")
    return 0


def do_finalize(
    zip_output: bool,
    public: bool | None,
    include_event_journal: bool,
    out: str | None = None,
    sign: bool = False,
) -> int:
    """Finalize the run into a distributable crate, applying the public/private policy."""
    ctx = ProjectContext.from_cwd()
    cfg = load_config(ctx.state_dir)
    resolved = cfg.privacy.public_by_default if public is None else public
    return finalize(
        ctx.state_dir,
        zip_output=zip_output,
        public=resolved,
        include_event_journal=include_event_journal,
        out=Path(out) if out else None,
        sign_fn=do_sign if sign else None,
    )


def do_redact(dry_run: bool, apply: bool, policy: str | None = None) -> int:
    ctx = ProjectContext.from_cwd()
    return redact_run(
        ctx.state_dir, apply=apply and not dry_run, policy=Path(policy) if policy else None
    )


def set_config(key: str, value: str) -> int:
    from dataclasses import fields, is_dataclass

    ctx = ProjectContext.from_cwd()
    cfg = load_config(ctx.state_dir)
    typed = _coerce_config_value(value)
    # Validate the key against the config schema rather than silently dropping unknown keys.
    if "." in key:
        section, field = key.split(".", 1)
        if section not in {f.name for f in fields(cfg)}:
            print(f"Unknown config section: {section!r}", file=sys.stderr)
            return 1
        sub = getattr(cfg, section)
        if not is_dataclass(sub):
            print(f"Config key {section!r} is not a section", file=sys.stderr)
            return 1
        if field not in {f.name for f in fields(sub)}:
            print(f"Unknown config field: {section}.{field}", file=sys.stderr)
            return 1
        setattr(sub, field, typed)
    else:
        if key not in {f.name for f in fields(cfg)}:
            print(f"Unknown config key: {key!r}", file=sys.stderr)
            return 1
        setattr(cfg, key, typed)
    write_config(ctx.state_dir, cfg)
    EventWriter(ctx.state_dir).append(
        "run.config.updated", {"key": key, "value": value}, source_kind="human_cli"
    )
    return 0


def _coerce_config_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.isdigit():
        return int(value)
    return value


def abort(reason: str = "") -> int:
    ctx = ProjectContext.from_cwd()
    EventWriter(ctx.state_dir).append(
        "run.aborted", {"reason": reason}, source_kind="human_cli"
    )
    return 0


def record_result(accepted: bool, text: str = "") -> int:
    ctx = ProjectContext.from_cwd()
    result = Redactor.for_state_dir(ctx.state_dir).redact_text(text)
    context = "human.accepted_result" if accepted else "human.rejected_result"
    writer = EventWriter(ctx.state_dir)
    writer.append(
        context,
        {"text": result.text},
        source_kind="human_cli",
        redacted=result.applied > 0,
    )
    if result.applied:
        writer.append(
            "redaction.applied",
            redaction_event_payload(context, result),
            source_kind="human_cli",
            redacted=True,
        )
    return 0


def hash_path(path: str) -> int:
    print(sha256_file(Path(path)))
    return 0


def import_ro_crate(path: str) -> int:
    from .adapters.imports import import_existing_ro_crate

    ctx = ProjectContext.from_cwd()
    try:
        events = import_existing_ro_crate(Path(path))
    except ValueError as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1
    writer = EventWriter(ctx.state_dir)
    for event in events:
        payload = cast(dict[str, Any], event["payload"])
        writer.append(
            str(event["event_type"]),
            payload,
            source_kind="materializer",
            observed=False,
            declared=True,
        )
    return 0


def _package_version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unknown"


def _probe_software(command_or_name: str) -> tuple[str | None, str | None]:
    executable = shutil.which(command_or_name)
    version = None
    if executable:
        proc = subprocess.run(
            [executable, "--version"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        output = (proc.stdout or proc.stderr).strip()
        if output:
            version = output.splitlines()[0]
    return version, executable
