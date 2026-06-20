"""The ``rcr`` argument parser: declare every subcommand and bind it via
``set_defaults(func=...)`` to a thin adapter over a `commands` handler, then
dispatch through ``args.func(args)``."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from . import commands
from .constants import PROFILE_CHOICES
from .inspect import inspect_crate, inspect_events, mermaid_graph


def _tri_state(positive: bool, negative: bool) -> bool | None:
    """Resolve a mutually-exclusive ``--x`` / ``--no-x`` flag pair into a tri-state.

    Returns True when only the positive flag is set, False when only the negative
    flag is set, and None when neither is set (let the handler apply its default).
    """
    return True if positive else False if negative else None


def _run_inspect(args: argparse.Namespace) -> int:
    from .context import ProjectContext

    state_dir = ProjectContext.from_cwd().state_dir
    if args.events:
        print(json.dumps(inspect_events(state_dir), indent=2, sort_keys=True))
    elif args.graph:
        print(mermaid_graph(state_dir))
    elif args.html:
        from .preview import render

        print(render(state_dir))
    else:
        print(json.dumps(inspect_crate(state_dir), indent=2, sort_keys=True))
    return 0


def _run_step(args: argparse.Namespace) -> int:
    if args.step_action == "start":
        return commands.step("start", args.step_id, args.workflow_step, args.description)
    return commands.step("end", args.step_id, status_value=args.status)


def _run_io(args: argparse.Namespace) -> int:
    return commands.declare_io(
        args.cmd,
        args.path,
        args.role,
        args.description,
        args.required,
        _tri_state(args.copy, args.reference),
        "public" if args.public else "private",
        args.existence,
    )


def _run_command(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return commands.run_command(command, args.step, _split(args.inputs), _split(args.outputs))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rcr")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start")
    p.add_argument("title", nargs="?", default="RO-Crate Run")
    p.add_argument("--mode", choices=["advisory", "monitored", "enforced"], default="monitored")
    p.add_argument("--profile", choices=PROFILE_CHOICES, default="auto")
    p.add_argument("--no-checkpoint", action="store_true")
    p.set_defaults(
        func=lambda a: commands.start(a.title, a.mode, a.profile, a.no_checkpoint)
    )

    p = sub.add_parser("resume")
    p.set_defaults(func=lambda a: commands.resume())

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=lambda a: commands.status(a.json))

    p = sub.add_parser("note")
    p.add_argument("text")
    vis = p.add_mutually_exclusive_group()
    vis.add_argument("--public", action="store_true")
    vis.add_argument("--private", action="store_true")
    p.set_defaults(func=lambda a: commands.note(a.text, a.public))

    p = sub.add_parser("decision")
    p.add_argument("text")
    p.add_argument("--rationale")
    vis = p.add_mutually_exclusive_group()
    vis.add_argument("--public", action="store_true")
    vis.add_argument("--private", action="store_true")
    p.set_defaults(func=lambda a: commands.decision(a.text, a.rationale, a.public))

    p = sub.add_parser("phase")
    p.add_argument("args", nargs="+")
    p.set_defaults(func=lambda a: commands.phase(a.args))

    p = sub.add_parser("step")
    step_sub = p.add_subparsers(dest="step_action", required=True)
    sp = step_sub.add_parser("start")
    sp.add_argument("step_id")
    sp.add_argument("--workflow-step")
    sp.add_argument("--description")
    sp = step_sub.add_parser("end")
    sp.add_argument("step_id")
    sp.add_argument("--status", default="completed", choices=["completed", "failed", "skipped"])
    p.set_defaults(func=_run_step)

    for name in ["input", "output"]:
        p = sub.add_parser(name)
        p.add_argument("path")
        p.add_argument("--role")
        p.add_argument("--description")
        p.add_argument("--required", action="store_true")
        vis = p.add_mutually_exclusive_group()
        vis.add_argument("--public", action="store_true")
        vis.add_argument("--private", action="store_true")
        p.add_argument(
            "--existence",
            choices=[
                "observed local",
                "observed remote",
                "generated",
                "expected",
                "missing",
                "declared-only",
            ],
        )
        group = p.add_mutually_exclusive_group()
        group.add_argument("--copy", action="store_true")
        group.add_argument("--reference", action="store_true")
        p.set_defaults(func=_run_io)

    p = sub.add_parser("parameter")
    p.add_argument("name")
    p.add_argument("value")
    p.add_argument("--formal-parameter")
    p.add_argument("--type")
    p.add_argument("--connect-from", help="source parameter @id of a ParameterConnection")
    p.add_argument("--connect-to", help="target parameter @id of a ParameterConnection")
    p.set_defaults(
        func=lambda a: commands.parameter(
            a.name, a.value, a.formal_parameter, a.type,
            connect_from=a.connect_from, connect_to=a.connect_to,
        )
    )

    p = sub.add_parser("container")
    p.add_argument("ref", help="image reference, e.g. docker.io/library/python:3.12")
    p.add_argument("--digest", help="sha256 digest")
    p.set_defaults(func=lambda a: commands.container(a.ref, a.digest))

    p = sub.add_parser("software")
    p.add_argument("command_or_name")
    p.add_argument("--version")
    p.add_argument("--type")
    p.set_defaults(func=lambda a: commands.software(a.command_or_name, a.version, a.type))

    p = sub.add_parser("run")
    p.add_argument("--step")
    p.add_argument("--inputs", default="")
    p.add_argument("--outputs", default="")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(func=_run_command)

    p = sub.add_parser("checkpoint")
    p.add_argument("--profile", choices=PROFILE_CHOICES, default="auto")
    p.set_defaults(func=lambda a: commands.do_checkpoint(a.profile))

    p = sub.add_parser("validate")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--public", action="store_true")
    p.set_defaults(func=lambda a: commands.do_validate(a.strict, a.json, a.public))

    p = sub.add_parser("finalize")
    p.add_argument("--zip", action="store_true")
    p.add_argument("--include-event-journal", action="store_true")
    p.add_argument("--sign", action="store_true")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--public", action="store_true")
    group.add_argument("--private", action="store_true")
    p.set_defaults(
        func=lambda a: commands.do_finalize(
            a.zip, _tri_state(a.public, a.private), a.include_event_journal, sign=a.sign
        )
    )

    p = sub.add_parser("inspect")
    p.add_argument("--events", action="store_true")
    p.add_argument("--crate", action="store_true")
    p.add_argument("--graph", action="store_true")
    p.add_argument("--html", action="store_true")
    p.set_defaults(func=_run_inspect)

    p = sub.add_parser("redact")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--policy")
    p.set_defaults(func=lambda a: commands.do_redact(a.dry_run, a.apply, a.policy))

    p = sub.add_parser("export")
    p.add_argument("--zip", action="store_true")
    p.add_argument("--out")
    # export never emits a public crate.
    p.set_defaults(
        func=lambda a: commands.do_finalize(
            zip_output=a.zip, public=False, include_event_journal=False, out=a.out
        )
    )

    p = sub.add_parser("hash")
    p.add_argument("path")
    p.set_defaults(func=lambda a: commands.hash_path(a.path))

    p = sub.add_parser("install-project")
    p.add_argument("--target", default=".")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=lambda a: commands.install_project(a.target, a.force))

    p = sub.add_parser("import-ro-crate")
    p.add_argument("path")
    p.set_defaults(func=lambda a: commands.import_ro_crate(a.path))

    p = sub.add_parser("sign")
    p.set_defaults(func=lambda a: commands.do_sign())

    p = sub.add_parser("verify")
    p.set_defaults(func=lambda a: commands.do_verify())

    p = sub.add_parser("config")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(func=lambda a: commands.set_config(a.key, a.value))

    p = sub.add_parser("abort")
    p.add_argument("reason", nargs="?", default="")
    p.set_defaults(func=lambda a: commands.abort(a.reason))

    for name in ["accept", "reject"]:
        p = sub.add_parser(name)
        p.add_argument("text", nargs="?", default="")
        p.set_defaults(func=lambda a: commands.record_result(a.cmd == "accept", a.text))

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd not in {"start", "install-project"}:
        from .context import ProjectContext
        from .recovery import ensure_recovered

        _state_dir = ProjectContext.from_cwd().state_dir
        if (_state_dir / "state.json").exists():
            ensure_recovered(_state_dir)
    return int(args.func(args))


def _split(value: str) -> list[str]:
    return [part for part in value.split(",") if part] if value else []
