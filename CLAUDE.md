# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ro-crate-run` is both a **Claude Code plugin** and a standalone **`rcr` CLI**. It captures provenance of human-in-the-loop computational work (commands run, files in/out, human decisions, software versions) and materializes it into [RO-Crate](https://www.researchobject.org/ro-crate/) 1.2 metadata conforming to the Process / Workflow / Provenance Run Crate 0.5 profiles. `SPEC.md` (~1900 lines) is the authoritative specification — consult it before changing behavior. The local `docs/` directory is intentionally gitignored and should not be treated as published project documentation.

## Commands

There is no global `python` on PATH — use the project venv (`.venv`). Develop against an editable install with all extras:

```bash
source .venv/bin/activate            # or prefix commands with .venv/bin/
python -m pip install -e '.[dev,shacl,signing]'
```

There is intentionally no CI for this repository. Run these local gates before claiming work is done:

```bash
python -m ruff check .
python -m mypy src                   # strict mode
python -m pytest --cov=ro_crate_run --cov-report=term-missing
```

Single test / subset:

```bash
python -m pytest tests/unit/test_validation_levels.py
python -m pytest tests/golden/test_golden_crates.py          # UPDATE_GOLDEN=1 regenerates fixtures
python -m pytest -k materialize
```

Real-world e2e suite (drives the actual `claude` CLI through the skill; opt-in, needs network + tokens):

```bash
RCR_E2E=1 python -m pytest tests/e2e -m e2e        # gated; skipped without RCR_E2E=1
python -m tests.e2e.run --jobs 6                   # standalone driver + coverage/validation report
python -m tests.e2e.run --name proc-minimal --keep # single scenario, retain temp dir
python -m pytest tests/e2e/test_e2e_coverage.py    # offline: surface-tag matrix sanity
```

`tests/e2e/` launches headless `claude` in throwaway temp projects, then validates the emitted crate (`assertions.assert_crate`: no dangling refs, descriptor + profile conformance, zero validation errors, scenario-specific entities, public leak scan). `coverage.py` is a 136-tag matrix of every command/flag/entity/field; `run.py` fails if the union of *passing* scenarios doesn't cover it. The harness puts `.venv/bin` on PATH so the skill's `rcr` + hooks resolve to repo `src/` (live fixes), and `protect_repo()` makes `src/skills/hooks/templates` read-only during runs so a bypassPermissions agent can't edit the code under test. Default model `sonnet`.

- ruff: line-length 100, `E501`/`UP007`/`UP045` ignored. Every module uses `from __future__ import annotations` (keep it — enables `X | None` on the 3.9 floor).
- Runtime deps: `rocrate`, `rdflib` (used for real JSON-LD expansion in validation), `filelock`. Optional extras: `pyshacl` (SHACL, has a `[[tool.mypy.overrides]]` so the gate passes with or without it) and `cryptography` (Ed25519 signing). Code that imports an optional dep must degrade gracefully and must not leave an unused `# type: ignore` (breaks strict mypy when the extra IS installed).

## Architecture

### Event-sourced core (the central design)
Everything is an append-only hash chain in `.ro-crate-run/events.ndjson`. Each event (`schema_version` `1.1.0`) carries a monotonic `sequence`, `previous_event_hash`/`event_hash`, a source-derived `actor` (`actor_for_source` maps `human_cli`→Person, model prompts→AIModel, hooks/CLI→SoftwareApplication), and the Claude `session_id`. `state.json` is a **derived, recoverable cache** — never a source of truth.

- **All event writes go through `EventWriter.append()`** (`journal.py`): file lock, fsync, hash-chain link, `state.sequence` bump, and a best-effort mirror to a remote journal when configured. Never write `events.ndjson` directly; never edit past events — only append.
- `recovery.py::ensure_recovered()` runs at the top of **every** CLI command and hook startup (not just `rcr resume`): it treats the journal as authoritative, marks abandoned `execution.command.started` as blocked, and emits `journal.repair.*`. `recovery.is_active_run()` is the single source for "is a run still active".
- Events are immutable. To change crate output you change how events are *projected*, not stored state.

### Materialization is pure projection (events → RO-Crate)
`materialize/run_model.py::build_run_model()` reduces events up to a high-water `sequence` into a `RunModel`. The crate is then assembled by composing pure builders, never by mutating a prior graph:
- `materialize/profiles.py::select_profile()` returns a `ProfileSelection` (profile, uri, confidence, evidence) from workflow/step/command evidence; `enrich_with_adapter()` lets the `adapters/` engines (cwl/nextflow/snakemake/galaxy) contribute engine + steps. CLI default profile is `auto`.
- `materialize/files.py::plan_file_inclusion()` applies the **file policy** (`include_declared_inputs/outputs`, `copy_mode` + per-declaration copy/reference, `ignore_patterns`, size limits, symlink-safe / out-of-root → reference) → `FilePlan`s.
- `materialize/mapping.py` holds the entity builders (`build_actors`, `build_software`, `build_command_action`, `build_file_entity`, `build_workflow`, `build_steps`, `build_git`, `build_environment`, `build_containers`, `build_dependencies`, `build_parameters`, `build_parameter_connections`, `build_notes_decisions`). Action `instrument`/`agent`/IDs must resolve to emitted entities — there is a `tests/graph_helpers.py::assert_no_dangling_refs` invariant.
- `materialize/builder.py::checkpoint()` is the orchestrator: it takes a **separate `.ro-crate-run/checkpoint.lock`** (NOT the append lock — that would self-deadlock), emits `crate.checkpoint.started`, builds the model, writes the crate, validates, and clears `dirty` only on `crate.checkpoint.completed` with a non-failed report.
- Bugs in crate output are almost always in the reducer (`run_model.py`) or a `mapping.py` builder, not in stored data.

### Layered validation (`validation/`)
`validator.py::validate_run()` builds a `ValidationContext` (`context.py::build_context`) and composes one function per level: `check_journal` (L0), `check_state` (L1, incl. id-map + dirty-accuracy), `check_rocrate` (L2, real JSON-LD expansion via `jsonld.py` using the **vendored contexts** in `src/ro_crate_run/assets/contexts/`), `check_profiles` (L3 process/workflow/provenance rules), `check_reproducibility` (L4 — 9 warnings), `check_privacy` (L5), plus optional `check_shacl`. Convention: reproducibility findings are warnings unless the code ends `_required`; `open_phase`/`open_step` are warnings; **all `privacy`-level findings are errors**. It honors `cfg.validation.*` flags (these are a live contract, not dead config) and populates `recommendations`.

### Privacy & public export
Redaction happens **before persistence** (`redaction.py`; custom patterns via `.ro-crate-run/secrets-redaction.json`, `Redactor.from_config`). `export.py::finalize()` for `--public` **stages the whole crate (including any embedded journal) into `staging/export-crate/`, runs the Level-5 gate over the staged dir, and only zips on success** — so prompts/secrets/journal can't leak. `rcr finalize --sign` / `rcr sign` adds an Ed25519 signature (keys in `.ro-crate-run/keys/`, never exported).

### Hooks & operating modes (`hooks.py`)
`handle_hook()` maps Claude lifecycle events (`EVENT_MAP`) into journal events; hooks no-op when no run exists and redact before persisting.
- **advisory**: never blocks. **monitored AND enforced**: the `Stop` hook checkpoints-when-stale, validates (incl. the public-export gate), and **blocks on critical failures** (materialization failure, missing required metadata/outputs, privacy findings, open phase/step). Advisory is the only non-blocking mode.
- **enforced `PreToolUse`** blocks four policy classes: raw substantive Bash (forcing `rcr run --`), writes into declared output roots, evidence-destroying commands, and secret-exfiltration patterns.
- `PostToolUse` emits `file.*` for Edit/Write but leaves Bash on `tool.completed` (the raw-Bash-bypass detector reads those). `SessionStart` emits `run.resumed` when resuming.

### Context / where state lives
`context.py::ProjectContext.from_cwd()` resolves the project root (`git rev-parse --show-toplevel`, fallback `.git` walk) and places state in `<root>/.ro-crate-run/`. `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_ROOT` override discovery.

## Critical gotcha: duplicated assets must stay in sync

The plugin layout and the packaged copy are **byte-identical duplicates with no automated sync**. After editing either side, verify with `diff -rq`:

| Plugin layout (repo root; `.claude-plugin/plugin.json`) | Packaged copy (used by `rcr install-project`) |
| --- | --- |
| `hooks/` | `src/ro_crate_run/assets/hooks/` |
| `skills/` (`ro-crate-run` + `ro-crate-run-admin`) | `src/ro_crate_run/assets/skills/` |
| `templates/` | `src/ro_crate_run/assets/templates/` |
| — | `src/ro_crate_run/assets/contexts/` (vendored RO-Crate / workflow-run JSON-LD, used by validation) |

```bash
diff -rq hooks src/ro_crate_run/assets/hooks
diff -rq skills src/ro_crate_run/assets/skills
diff -rq templates src/ro_crate_run/assets/templates
```

The `rcr` launchers (`skills/.../scripts/rcr`) and every `hooks/rocrate_*.py` import a `_bootstrap` shim that puts `ro_crate_run` on `sys.path` (resolving via `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PROJECT_DIR` or script-relative), so they work without a pip install; `rcr install-project` vendors the package into `.claude/lib/`. All real logic lives in `src/ro_crate_run/`; wrappers are thin. Adding a hook event means: new wrapper (both copies), an entry in `hooks/hooks.json` (both copies), and a case in `hooks.py::EVENT_MAP`/`handle_hook`.

## Conventions

- Config (`config.json`) is a **contract**: every flag must change behavior and have a test proving it. Dataclasses in `models.py` are hand-(de)serialized in `state.py::_from_dict`/`_to_json` — register new nested config dataclasses there.
- Golden crates: `tests/golden/` (harness `_compare.py`, `UPDATE_GOLDEN=1` to regenerate) plus `examples/*/expected/`. When materialization changes, regenerate deliberately and confirm the no-dangling-ref invariant.
- New event types must be registered in the `constants.py` event vocabulary (the L0 validator checks against it).
- Commits follow Conventional Commits (`feat:`/`fix:`/`refactor:`/`test:`); `main` is the local trunk.
