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

`tests/e2e/` launches headless `claude` in throwaway temp projects, then validates the emitted crate (`assertions.assert_crate`: no dangling refs, descriptor + profile conformance, zero validation errors, scenario-specific entities, public leak scan). `coverage.py` is a 145-tag matrix of every command/flag/entity/field; `run.py` fails if the union of *passing* scenarios doesn't cover it. Per run the harness snapshots `src/` to a throwaway dir and points the scenario's `PYTHONPATH` there, so the skill's `rcr` + hooks import the snapshot — live fixes are picked up each run, but a bypassPermissions agent's edits to repo `src/` are inert (it is not on the scenario's import path), and edits to the snapshot are caught by a post-run integrity hash (`protect_repo()` read-onlys the source as a secondary guard). Default model `sonnet`.

- ruff: line-length 100, `E501`/`UP007`/`UP045` ignored. Every module uses `from __future__ import annotations` (keep it — enables `X | None` on the 3.9 floor).
- Runtime deps: `rocrate`, `rdflib` (used for real JSON-LD expansion in validation), `filelock`. Optional extras: `pyshacl` (SHACL) and `cryptography` (Ed25519 signing) — each has a `[[tool.mypy.overrides]]` (`ignore_missing_imports`) so the strict gate passes with or without it installed. Code that imports an optional dep must degrade gracefully (e.g. `signing.py` sets `_CRYPTO_AVAILABLE` and raises only when used) and must not leave an unused `# type: ignore` (breaks strict mypy when the extra IS installed).

## Architecture

### Event-sourced core (the central design)
Everything is an append-only hash chain in `.ro-crate-run/events.ndjson`. Each event (`schema_version` `1.1.0`) carries a monotonic `sequence`, `previous_event_hash`/`event_hash`, a source-derived `actor` (`actor_for_source` maps `human_cli`→Person, model/hook/CLI sources→SoftwareApplication, `ci`→System), and the Claude `session_id`. `state.json` is a **derived, recoverable cache** — never a source of truth.

- **All event writes go through `EventWriter.append()`** (`journal.py`): file lock, fsync, hash-chain link, `state.sequence` bump, and a best-effort mirror to a remote journal when configured. Never write `events.ndjson` directly; never edit past events — only append. The one other sanctioned mutator is `EventWriter.rewrite_chain()` (a full-chain atomic relink under the append lock, used by `rcr redact`); `events.verify_hash_chain()` is the shared chain-integrity check used by both recovery and L0 validation.
- `recovery.py::ensure_recovered()` runs at the top of **every** CLI command and hook startup (not just `rcr resume`): it treats the journal as authoritative, marks abandoned `execution.command.started` as blocked, and emits `journal.repair.*`. `recovery.is_active_run()` is the single source for "is a run still active".
- Events are immutable. To change crate output you change how events are *projected*, not stored state.

### Materialization is pure projection (events → RO-Crate)
`materialize/run_model.py::build_run_model()` reduces events up to a high-water `sequence` into a `RunModel`, dispatching each event through a `_PROJECTORS` (event-type → `_reduce_*`) registry in one sequential pass — add an event family by registering a reducer, not by extending a branch ladder. The agent's own observed activity (file edits, raw commands, subagents, tool uses, …) is grouped under `RunModel.agent_activity` (an `AgentActivity` sub-dataclass) and collapsed to one record per task/tool inside the reducer (builders stay pure 1:1 mappers). The crate is then assembled by composing pure builders, never by mutating a prior graph:
- `materialize/profiles.py::select_profile()` returns a `ProfileSelection` (profile, uri, confidence, evidence) from workflow/step/command evidence; `enrich_with_adapter()` lets the `adapters/` engines (cwl/nextflow/snakemake/galaxy) contribute engine + steps. CLI default profile is `auto`. Per-profile facts (uri, extra-`conformsTo`, workflow-like-ness) live in one `constants.ProfileSpec`/`PROFILES` registry that `PROFILE_URIS`/`WORKFLOW_LIKE_PROFILES`/`PROFILE_CHOICES` derive from; workflow-definition detection and engine naming go through `adapters.engine_for_path()`/`is_workflow_definition()` (pure path-string, derived from each adapter's declared suffixes/filenames).
- `materialize/files.py::plan_file_inclusion()` applies the **file policy** (`include_declared_inputs/outputs`, `copy_mode` + per-declaration copy/reference, `ignore_patterns`, size limits, symlink-safe / out-of-root → reference) → `FilePlan`s.
- `materialize/mapping/` is a package (`actors`/`actions`/`file_entities`/`parameters`/`workflow`/`provenance`/`_helpers`, all re-exported from `mapping/__init__.py` so callers keep `from ...materialize import mapping; mapping.build_X`). It holds the entity builders (`build_actors`, `build_software`, `build_command_action`, `build_file_entity`, `build_workflow`, `build_steps`, `build_git`, `build_environment`, `build_containers`, `build_dependencies`, `build_parameters`, `build_parameter_connections`, `build_notes_decisions`). Builders pull shared literals/helpers from `constants.py` (action-status/profile/URI constants, `ROOT_DATASET_ID`, `BYTES_PER_MB`, `is_web_id`), `ids.py` (`relative_file_id`/`file_ref`), `events.py` (the actor roster + `crate_actor_id`), `fs.py` (hash/file-record primitives + `bare_sha256`/`write_json`, formerly `files.py`), and `mapping/_helpers.py` (the shared JSON-LD node constructors `ref`/`property_value`/`sha256_identifier`/`fragment_id`/`root_ref`/`root_creative_work`/`software_application`/`ensure_software`, plus the unified `FILE_OPS` vocabulary that single-sources each file op's `file.*` event type AND its Create/Update/DeleteAction type — `FILE_OP_TYPE` is a derived view of it, and `hooks.py`/`run_model.py` route through it). Open-coding a `{"@id": …}`, `PropertyValue`, `SoftwareApplication`, `#actor/*`, or `#prefix/seq` node by hand is a smell — route it through these. Action `instrument`/`agent`/IDs must resolve to emitted entities — there is a `tests/graph_helpers.py::assert_no_dangling_refs` invariant.
- `materialize/builder.py::checkpoint()` is the orchestrator: it takes a **separate `.ro-crate-run/checkpoint.lock`** (NOT the append lock — that would self-deadlock), emits `crate.checkpoint.started`, builds the model, writes the crate, validates, and clears `dirty` only on `crate.checkpoint.completed` with a non-failed report. Crate assembly is `write_crate()`, decomposed into ordered `_emit_*(_WriteCtx)` section emitters (the hasPart backfill runs last) — preserve section order when editing.
- Bugs in crate output are almost always in the reducer (`run_model.py`) or a `mapping/` builder, not in stored data.

### Layered validation (`validation/`)
`validator.py::validate_run()` builds a `ValidationContext` (`context.py::build_context`; exposes a cached `entities` @id index) and composes one checker per level via an ordered `CHECKS` registry: `check_journal` (L0), `check_state` (L1, incl. id-map + dirty-accuracy), `check_rocrate` (L2, real JSON-LD expansion via `jsonld.py` using the **vendored contexts** in `src/ro_crate_run/assets/contexts/`), `check_profile` (L3 process/workflow/provenance rules), `check_reproducibility` (L4 reproducibility warnings), `check_privacy` (L5), plus optional `check_shacl`. Shared `@type`-list / action-detection helpers live in `validation/graphview.py` (a neutral, dependency-free module also used by `inspect.py`). Severity is **structural**: each checker constructs findings via a level-bound `validation/_findings.py::level_finding` factory (e.g. `partial(level_finding, LEVEL_JOURNAL)`) carrying `severity="error"|"warning"`, and `validator._is_error` is just a field read. Level names are `constants.LEVEL_*` constants (referenced by the checkers and the Stop hook, not bare strings). By convention privacy findings are always errors and `open_phase`/`open_step` are warnings; the `_required` code suffix is retained only as the recommendations-lookup key (`tests/unit/test_recommendation_codes.py` guards that every recommendation key maps to an emittable code). It honors `cfg.validation.*` flags (these are a live contract, not dead config) and populates `recommendations`.

### Privacy & public export
Redaction happens **before persistence** (`redaction.py`; custom patterns via `.ro-crate-run/secrets-redaction.json`, `Redactor.from_config`). `export.py::finalize()` for `--public` **stages the whole crate (including any embedded journal) into `staging/export-crate/`, runs the Level-5 gate over the staged dir, and only zips on success** — so prompts/secrets/journal can't leak. `rcr finalize --sign` / `rcr sign` adds an Ed25519 signature (keys in `.ro-crate-run/keys/`, never exported).

### Hooks & operating modes (`hooks.py`)
`handle_hook()` maps Claude lifecycle events (`EVENT_MAP`) into journal events; hooks no-op when no run exists and redact before persisting.
- **advisory**: never blocks. **monitored AND enforced**: the `Stop` hook checkpoints-when-stale, validates (incl. the public-export gate), and **blocks on critical failures** (materialization failure, missing required metadata/outputs, privacy findings, open phase/step). Advisory is the only non-blocking mode.
- **enforced `PreToolUse`** blocks four policy classes via an ordered `(predicate, reason)` policy registry: raw substantive Bash (forcing `rcr run --`), writes into declared output roots, evidence-destroying commands, and secret-exfiltration patterns. The monitored-mode Stop-blocking codes/levels are declared module data referenced by the Stop hook (not re-listed inline).
- `PostToolUse` emits `file.*` for Edit/Write but leaves Bash on `tool.completed` (the raw-Bash-bypass detector reads those). `SessionStart` emits `run.resumed` when resuming.

### Context / where state lives
`context.py::ProjectContext.from_cwd()` resolves the project root (`git rev-parse --show-toplevel`, fallback `.git` walk) and places state in `<root>/.ro-crate-run/`. `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_ROOT` override discovery.

## Critical gotcha: duplicated assets must stay in sync

The plugin layout and the packaged copy are **byte-identical duplicates**. This is now enforced by `tests/unit/test_asset_sync.py` (byte-identity of the asset trees plus every `_bootstrap.py` / `hooks.json` copy), but after editing either side still verify with `diff -rq`:

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

The `rcr` launchers (`skills/.../scripts/rcr`) and the single generic `hooks/rocrate_hook.py` (every `hooks.json` entry invokes it with the Claude event name as its argument) import a `_bootstrap` shim that puts `ro_crate_run` on `sys.path` (resolving via `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PROJECT_DIR` or script-relative), so they work without a pip install; `rcr install-project` (logic in `install.py`) vendors the package into `.claude/lib/`. All real logic lives in `src/ro_crate_run/`; wrappers are thin (the skill routes every subcommand through `scripts/rcr` — there are no per-command `rocrate_*.py` wrapper scripts). Adding a hook event means: an entry in `hooks/hooks.json` (both copies) pointing at `rocrate_hook.py <EventName>`, registering the event in `constants.py::EVENT_TYPES`, and a handler in `hooks.py::EVENT_MAP`/`handle_hook` (per-event `_on_*` handlers) — `tests/unit/test_hook_event_sync.py` guards that every `hooks.json` event is mapped and every mapped target is a registered event type.

## Conventions

- Config (`config.json`) is a **contract**: every flag must change behavior and have a test proving it. Dataclasses in `models.py` are (de)serialized by `state.py::_from_dict` (generic dataclass recursion via `typing.get_type_hints`) / `_to_json`; new nested config dataclasses are handled automatically — no per-type registration needed. The hash size gate is single-sourced in `HashPolicy.max_hash_bytes()` (it honors `hash_large_files` → `sys.maxsize`); every hashing site (checkpoint, runner snapshots, `rcr input`) must call it, never recompute `max_file_size_mb * BYTES_PER_MB` inline. `rcr config` coerces a value to the field's declared type before storing.
- Shared low-level seams to use (don't re-spell them): `clock.py` (`utc_now`, formerly `time.py` — renamed so it no longer shadows stdlib `time`); `fs.py::atomic_write_text`/`write_json`; `proc.py::run_capture` (the timeout-guarded subprocess wrapper behind `git._git` and `software_probe`); the `constants.py` vocabularies (`LEVEL_*`, `EXISTENCE_OBSERVED/ABSENT` + `is_observed`/`is_absent`, `SUBAGENT_EVENT_TYPES`, `events.SourceKind`); `EventWriter.append`/`rewrite_chain` share `_mirror_lines`/`_bump_state`/`apply_dirty_effect`.
- Golden crates: `tests/golden/` (harness `_compare.py`, `UPDATE_GOLDEN=1` to regenerate; fixtures are per-scenario `expected-dimensions.json` files). When materialization changes, regenerate deliberately and confirm the no-dangling-ref invariant.
- New event types must be registered in the `constants.py` event vocabulary (the L0 validator checks against it), and projected by registering a `_reduce_*` in `run_model.py::_PROJECTORS` if they should appear in the crate.
- Host/OCI/discovery domain helpers extracted from the CLI layer live in `oci.py` (`parse_image_ref`) and `software_probe.py` (`probe_software`/`scan_lockfiles`/`classify_existence`), re-exported from `commands.py` so the CLI bindings are unchanged.
- Commits follow Conventional Commits (`feat:`/`fix:`/`refactor:`/`test:`); `main` is the local trunk.
