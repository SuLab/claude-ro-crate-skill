from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import commands
from .inspect import inspect_crate, inspect_events, mermaid_graph


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rcr")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("title", nargs="?", default="RO-Crate Run")
    p.add_argument("--mode", choices=["advisory", "monitored", "enforced"], default="monitored")
    p.add_argument(
        "--profile", choices=["process", "workflow", "provenance", "auto"], default="auto"
    )
    p.add_argument("--no-checkpoint", action="store_true")
    sub.add_parser("resume")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("note")
    p.add_argument("text")
    p.add_argument("--public", action="store_true")
    p.add_argument("--private", action="store_true")
    p = sub.add_parser("decision")
    p.add_argument("text")
    p.add_argument("--rationale")
    p.add_argument("--public", action="store_true")
    p.add_argument("--private", action="store_true")
    p = sub.add_parser("phase")
    p.add_argument("args", nargs="+")
    p = sub.add_parser("step")
    step_sub = p.add_subparsers(dest="step_action", required=True)
    sp = step_sub.add_parser("start")
    sp.add_argument("step_id")
    sp.add_argument("--workflow-step")
    sp.add_argument("--description")
    sp = step_sub.add_parser("end")
    sp.add_argument("step_id")
    sp.add_argument("--status", default="completed", choices=["completed", "failed", "skipped"])
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
    p = sub.add_parser("parameter")
    p.add_argument("name")
    p.add_argument("value")
    p.add_argument("--formal-parameter")
    p.add_argument("--type")
    p.add_argument("--connect-from", help="source parameter @id of a ParameterConnection")
    p.add_argument("--connect-to", help="target parameter @id of a ParameterConnection")
    p = sub.add_parser("container")
    p.add_argument("ref", help="image reference, e.g. docker.io/library/python:3.12")
    p.add_argument("--digest", help="sha256 digest")
    p = sub.add_parser("software")
    p.add_argument("command_or_name")
    p.add_argument("--version")
    p.add_argument("--type")
    p = sub.add_parser("run")
    p.add_argument("--step")
    p.add_argument("--inputs", default="")
    p.add_argument("--outputs", default="")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("checkpoint")
    p.add_argument(
        "--profile", choices=["process", "workflow", "provenance", "auto"], default="auto"
    )
    p = sub.add_parser("validate")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("finalize")
    p.add_argument("--zip", action="store_true")
    p.add_argument("--include-event-journal", action="store_true")
    p.add_argument("--sign", action="store_true")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--public", action="store_true")
    group.add_argument("--private", action="store_true")
    p = sub.add_parser("inspect")
    p.add_argument("--events", action="store_true")
    p.add_argument("--crate", action="store_true")
    p.add_argument("--graph", action="store_true")
    p.add_argument("--html", action="store_true")
    p = sub.add_parser("redact")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--policy")
    p = sub.add_parser("export")
    p.add_argument("--zip", action="store_true")
    p.add_argument("--out")
    p = sub.add_parser("hash")
    p.add_argument("path")
    p = sub.add_parser("install-project")
    p.add_argument("--target", default=".")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("import-ro-crate")
    p.add_argument("path")
    sub.add_parser("sign")
    sub.add_parser("verify")
    p = sub.add_parser("config")
    p.add_argument("key")
    p.add_argument("value")
    p = sub.add_parser("abort")
    p.add_argument("reason", nargs="?", default="")
    for name in ["accept", "reject"]:
        p = sub.add_parser(name)
        p.add_argument("text", nargs="?", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd not in {"start", "install-project"}:
        from .context import ProjectContext
        from .recovery import ensure_recovered

        _state_dir = ProjectContext.from_cwd().state_dir
        if (_state_dir / "state.json").exists():
            ensure_recovered(_state_dir)
    if args.cmd == "start":
        return commands.start(args.title, args.mode, args.profile, args.no_checkpoint)
    if args.cmd == "resume":
        return commands.resume()
    if args.cmd == "status":
        return commands.status(args.json)
    if args.cmd == "note":
        return commands.note(args.text, args.public)
    if args.cmd == "decision":
        return commands.decision(args.text, args.rationale, args.public)
    if args.cmd == "phase":
        return commands.phase(args.args)
    if args.cmd == "step":
        if args.step_action == "start":
            return commands.step("start", args.step_id, args.workflow_step, args.description)
        return commands.step("end", args.step_id, status_value=args.status)
    if args.cmd in {"input", "output"}:
        return commands.declare_io(
            args.cmd,
            args.path,
            args.role,
            args.description,
            args.required,
            True if args.copy else False if args.reference else None,
            "public" if args.public else "private",
            args.existence,
        )
    if args.cmd == "parameter":
        return commands.parameter(
            args.name, args.value, args.formal_parameter, args.type,
            connect_from=args.connect_from, connect_to=args.connect_to,
        )
    if args.cmd == "container":
        return commands.container(args.ref, args.digest)
    if args.cmd == "software":
        return commands.software(args.command_or_name, args.version, args.type)
    if args.cmd == "run":
        command = list(args.command)
        if command and command[0] == "--":
            command = command[1:]
        return commands.run_command(command, args.step, _split(args.inputs), _split(args.outputs))
    if args.cmd == "checkpoint":
        return commands.do_checkpoint(args.profile)
    if args.cmd == "validate":
        return commands.do_validate(args.strict, args.json)
    if args.cmd == "finalize":
        public: bool | None = True if args.public else False if args.private else None
        return commands.do_finalize(args.zip, public, args.include_event_journal, sign=args.sign)
    if args.cmd == "inspect":
        from .context import ProjectContext

        state_dir = ProjectContext.from_cwd().state_dir
        if args.events:
            print(inspect_events(state_dir))
        elif args.graph:
            print(mermaid_graph(state_dir))
        elif args.html:
            from .preview import render

            print(render(state_dir))
        else:
            print(inspect_crate(state_dir))
        return 0
    if args.cmd == "redact":
        return commands.do_redact(args.dry_run, args.apply, args.policy)
    if args.cmd == "export":
        return commands.do_finalize(args.zip, False, False, args.out)
    if args.cmd == "hash":
        return commands.hash_path(args.path)
    if args.cmd == "install-project":
        return commands.install_project(args.target, args.force)
    if args.cmd == "import-ro-crate":
        return commands.import_ro_crate(args.path)
    if args.cmd == "sign":
        return commands.do_sign()
    if args.cmd == "verify":
        return commands.do_verify()
    if args.cmd == "config":
        return commands.set_config(args.key, args.value)
    if args.cmd == "abort":
        return commands.abort(args.reason)
    if args.cmd in {"accept", "reject"}:
        return commands.record_result(args.cmd == "accept", args.text)
    return 2

def _split(value: str) -> list[str]:
    return [part for part in value.split(",") if part] if value else []
