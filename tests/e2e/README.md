# Real-world e2e tests (claude CLI → ro-crate-run skill)

These tests launch the real `claude` CLI headlessly against the `ro-crate-run` skill
in throwaway temp projects, then validate the emitted RO-Crate. They are the only
tests that exercise the real `claude` + skill + hooks end to end (the rest of the
suite drives `rcr`/the Python API in-process).

## How it works

`harness.run_scenario` creates an isolated temp git project, seeds files, and snapshots
`src/ro_crate_run` into a throwaway dir (`snapshot_source()`). It launches `claude -p`
with `PATH=<repo>/.venv/bin:$PATH`, `PYTHONPATH=<snapshot>`, and `CLAUDE_PROJECT_DIR=<tmp>`:
the skill `rcr` and hooks import `ro_crate_run` from the snapshot (NOT the repo `src/`,
which is never imported — a bypassPermissions agent editing repo `src/` is inert), while
`CLAUDE_PROJECT_DIR` only places run state under the temp project. The snapshot is
recreated from the current `src/` each run, so live fixes are picked up per-run (but via
the per-run snapshot, not by importing `src/` directly or via `CLAUDE_PROJECT_DIR`). It
then loads `<tmp>/.ro-crate-run/ro-crate/ro-crate-metadata.json` and runs
`rcr validate --json` / `rcr status --json`. `assertions.assert_crate` runs the
standard validation battery (no dangling refs, descriptor + profile conformance,
zero validation errors, scenario-specific entity/property checks, public leak scan).

## Run

- pytest (gated):       `RCR_E2E=1 .venv/bin/python -m pytest tests/e2e -m e2e -v`
- standalone (all):     `.venv/bin/python -m tests.e2e.run --jobs 4`
- one scenario:         `.venv/bin/python -m tests.e2e.run --name proc-minimal --keep`
- one area:             `.venv/bin/python -m tests.e2e.run --area profiles --jobs 4`
- coverage gate (offline, no claude): `.venv/bin/python -m pytest tests/e2e/test_e2e_coverage.py`
- harness unit (offline, no claude):  `.venv/bin/python -m pytest tests/e2e/test_harness_unit.py`

Default model is `sonnet`; pass `--model opus` for spot-checks. Each scenario runs in
its own temp dir and never touches the real repo. `results/` (gitignored) holds the
JSON report and, with `--keep`, the temp workdir paths for debugging.

## Cost

Each scenario is one headless `claude` session (~30–90s + tokens). Use `--name`/`--area`
and `--jobs` while iterating; run the full suite before claiming done.
