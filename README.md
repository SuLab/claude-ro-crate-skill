# RO-Crate Run

`ro-crate-run` is a Claude Code plugin and standalone `rcr` CLI for recording
human-in-the-loop computational provenance and materializing it as RO-Crate 1.2
metadata. It captures the commands that were run, declared inputs and outputs,
human decisions, parameters, software, validation reports, and release decisions
needed to explain and reproduce a run.

The package is designed for research and analysis sessions where an agent,
human operator, and local command-line tools collaborate on a computational
result. It keeps an append-only event journal under `.ro-crate-run/`, derives a
recoverable state cache from that journal, and writes RO-Crate metadata during
checkpoints and finalization.

## What It Does

- Records provenance events for Claude Code sessions, terminal commands, file
  declarations, parameters, software, workflow phases, workflow steps, notes,
  and human accept/reject decisions.
- Wraps substantive shell commands with `rcr run --` so command start,
  completion, exit status, stdout/stderr summaries, declared inputs, and
  declared outputs are captured consistently.
- Installs Claude Code skills and hooks into a target project so provenance is
  captured from both direct skill invocations and Claude lifecycle events.
- Supports Process Run Crate, Workflow Run Crate, and Provenance Run Crate style
  materialization, with automatic profile selection when enough workflow
  evidence is available.
- Generates checkpoints from the event journal, not from mutable prior crate
  output, so crate metadata can be rebuilt from recorded facts.
- Validates journal integrity, derived state, RO-Crate structure, profile
  requirements, reproducibility warnings, and public-export privacy gates.
- Redacts secret-like values before persistence where feasible and blocks public
  export when privacy findings remain.
- Supports private and public finalization, zip export, optional event-journal
  inclusion, Ed25519 signing, recovery from interrupted commands, and inspection
  of recorded events and crate structure.

## Repository Layout

- `src/ro_crate_run/` - Python package and CLI implementation.
- `hooks/` - Claude Code hook wrappers used by the plugin checkout.
- `skills/` - Claude Code skills exposed by the plugin checkout.
- `src/ro_crate_run/assets/` - packaged copies of hooks, skills, templates, and
  vendored JSON-LD contexts used by `rcr install-project`.
- `templates/` - settings and preview templates.
- `examples/` - minimal example projects for process, workflow, provenance, and
  privacy-safe public crates.
- `tests/` - unit, integration, and golden-crate tests.

The plugin checkout and packaged assets intentionally duplicate the hook, skill,
and template files. Keep these copies byte-identical after edits:

```bash
diff -rq hooks src/ro_crate_run/assets/hooks
diff -rq skills src/ro_crate_run/assets/skills
diff -rq templates src/ro_crate_run/assets/templates
```

## Install For Local Development

Use the project virtual environment or create one, then install the package in
editable mode:

```bash
python3 -m pip install -e '.[dev,shacl,signing]'
```

The CLI entry point is `rcr`:

```bash
rcr --help
```

## Use The CLI Directly

A minimal process run looks like this:

```bash
rcr start "Demo analysis"
rcr input data/input.tsv --role input --description "Input table" --public
rcr run -- python3 analysis.py data/input.tsv results/output.tsv
rcr output results/output.tsv --role result --description "Analysis output" --public
rcr decision "Accepted the generated output" --rationale "Checks passed" --public
rcr checkpoint
rcr validate --strict
rcr finalize --zip --public
```

Common commands:

- `rcr start "Title"` - start a new provenance run.
- `rcr resume` - resume an existing run.
- `rcr status` - show run status.
- `rcr note` and `rcr decision` - record observations and human rationale.
- `rcr phase` and `rcr step` - structure longer workflows.
- `rcr input`, `rcr output`, `rcr parameter`, and `rcr software` - declare
  reproducibility metadata.
- `rcr run -- <command>` - execute and record substantive shell commands.
- `rcr checkpoint` - materialize the current RO-Crate metadata.
- `rcr validate --strict` - run strict validation.
- `rcr inspect --events`, `rcr inspect --graph`, or `rcr inspect --html` -
  inspect recorded provenance.
- `rcr redact --dry-run` and `rcr redact --apply` - review or apply redaction.
- `rcr finalize --zip --public` - run the public privacy gate and create a
  release package.
- `rcr sign` or `rcr finalize --sign` - sign finalized crate metadata.

## Use The Claude Code Plugin

From this repository checkout:

```bash
claude --plugin-dir .
```

Then invoke the skill commands from Claude Code:

```text
/ro-crate-run:ro-crate-run start "Demo analysis"
/ro-crate-run:ro-crate-run run -- python3 analysis.py
/ro-crate-run:ro-crate-run checkpoint
/ro-crate-run:ro-crate-run validate --strict
/ro-crate-run:ro-crate-run finalize --zip --public
```

To install the packaged skill and hooks into another project:

```bash
rcr install-project --target /path/to/project
```

`install-project` writes the `ro-crate-run` and `ro-crate-run-admin` skills, hook wrappers, vendored
Python package files, and `.claude/settings.json` hook configuration into the
target project. Use `--force` to replace an existing installed copy.

## Skills

This plugin provides two Claude Code skills.

### RO-Crate Run

`RO-Crate Run` is the normal model-invocable skill. Use it whenever an agent is
doing provenance-relevant work in a project: running commands, editing files
that form part of an analysis, producing outputs, making workflow decisions, or
preparing a crate for validation.

The skill routes requests to the bundled `rcr` launcher and expects the agent to:

- Start or resume a run before provenance-relevant work.
- Run substantive shell commands through `rcr run --`.
- Declare important inputs and outputs with `rcr input` and `rcr output`.
- Record human choices with `rcr decision` and observations with `rcr note`.
- Use `rcr phase` and `rcr step` for multi-stage work.
- Checkpoint after major phases.
- Run `rcr status` before final answers when a run is active.
- Prefer the Process Run Crate profile unless there is concrete workflow
  evidence for Workflow Run Crate or Provenance Run Crate materialization.
- Treat hook-captured events as observed facts and user-provided metadata as
  declarations.
- Ask for missing metadata only when it is required for profile validity,
  privacy decisions, or meaningful reproducibility.

The skill includes reference files for mapping policy, profile selection,
validation rules, and privacy policy. The agent loads those references only when
the task needs that detail.

### RO-Crate Run Admin

`RO-Crate Run Admin` is intentionally marked as not model-invocable. It covers
operations that are destructive or release-affecting and should only happen
after explicit human intent:

- `rcr redact --apply` - rewrite the event journal with redactions applied while
  preserving a pre-redaction copy and tombstone events.
- `rcr finalize --public` - run the public privacy gate and create a releasable
  crate only if the gate passes.
- `rcr sign` - sign finalized crate metadata with the project Ed25519 key.

Before any admin operation, confirm intent and run:

```bash
rcr validate --strict
```

## Hooks And Modes

The plugin declares hooks in `hooks/hooks.json`. Hook wrappers no-op when no run
is active, redact before persistence, and record Claude lifecycle events such as
session start, user prompts, tool use, file edits, stop events, compact events,
and task/subagent activity.

Operating modes:

- `advisory` - record provenance without blocking.
- `monitored` - run stop-time checks and block on critical failures.
- `enforced` - additionally blocks raw substantive Bash, writes into declared
  output roots, evidence-destroying commands, and secret-exfiltration patterns.

## Privacy And Public Export

Private runs may retain local provenance detail under `.ro-crate-run/`. Public
exports are stricter: prompts, private event journals, unrestricted logs, full
environments, source code, and git diffs are excluded by default. Public export
stages the crate, runs the Level-5 privacy gate over the staged output, and only
creates a zip when the gate passes.

## Validation

Validation covers:

- event-journal hash-chain integrity;
- derived-state consistency;
- RO-Crate structure and JSON-LD expansion;
- Process, Workflow, and Provenance Run Crate profile requirements;
- reproducibility warnings;
- privacy errors for public release;
- optional SHACL validation when `pyshacl` is installed.

Run local checks before publishing changes:

```bash
python3 -m ruff check .
python3 -m mypy src
python3 -m pytest --cov=ro_crate_run --cov-report=term-missing
```

This repository intentionally has no CI configuration. Run the local gates above
when changing behavior.

## License

Apache License 2.0. See [LICENSE](LICENSE).
