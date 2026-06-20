# Validation Rules

## Validation Levels (SPEC §17)

| Level | Name                  | What is checked                                                     |
|-------|-----------------------|---------------------------------------------------------------------|
| 0     | Journal Integrity     | Hash chain continuity, no unterminated started events (active run exempt) |
| 1     | State Consistency     | State fields match event projections; id-map accuracy              |
| 2     | RO-Crate Structure    | JSON-LD expansion; required entities present; descriptor conformsTo |
| 3     | Profile Rules         | Process/Workflow/Provenance-specific required fields                |
| 4     | Reproducibility       | Warnings for missing versions, missing checksums, non-determinism  |
| 5     | Public Export Gate    | Scans all files (including embedded journal) for sensitive data     |

## Level 0 — Journal Integrity

- Every event must have a valid `event_hash` computed from its canonical JSON.
- `previous_event_hash` must match the `event_hash` of the preceding event.
- Unterminated `execution.command.started` is an ERROR unless `active_run` flag is set (then WARNING).
- All events must have `schema_version = "1.1.0"`.

## Level 1 — State Consistency

- `state.run_id` must match all events' `run_id`.
- `state.sequence` must equal the number of events in the journal.
- `id-map.json` must be valid JSON and its `event_to_entity`/`path_to_entity`/`step_to_entity` sections must each be an object.

## Level 2 — RO-Crate Structure

- `ro-crate-metadata.json` must be valid JSON.
- The descriptor entity must have `conformsTo: https://w3id.org/ro/crate/1.2`.
- Root entity `./` must have `name`, `description`, `datePublished`, `license`.
- JSON-LD expansion via rdflib must not produce errors.

## Level 3 — Profile Rules

**Process Run Crate:**
- At least one `CreateAction` or `Action` with a valid `instrument`.

**Workflow Run Crate (adds):**
- A `ComputationalWorkflow` entity with `programmingLanguage`.
- A workflow engine `SoftwareApplication`.

**Provenance Run Crate (adds):**
- At least one `HowToStep` entity.
- Each step-level `CreateAction` links via `ControlAction`.

## Strict Mode Additions

With `--strict`: policy-gated reproducibility findings (those whose code ends in `_required`) become errors, a Process Run Crate with zero actions becomes an error, and a SHACL shapes check runs (when the `pyshacl` extra is installed).

## Finding Codes

- `hash_chain_mismatch` / `event_hash_mismatch` — broken hash chain (Level 0)
- `unterminated_command` — command with no terminal event (Level 0)
- `missing_software_versions` — no tool versions declared (Level 4, warning)
- `missing_environment_summary` — no environment observed (Level 4, warning)
- `referenced_file_missing` / `metadata_missing` — missing required crate entity (Level 2)
- `action_missing_instrument` / `workflow_missing_entity` — profile rule violation (Level 3)
- `secret_pattern` / `env_var_outside_allowlist` — public-export privacy leak (Level 5)

## Public Release Gate Conditions (Level 5)

Fails closed (blocks export) when:
- Any event payload contains a secret regex match (token, password, key).
- A captured file path matches a denylist pattern (`.env`, `*.pem`, `id_rsa`, etc.).
- The embedded event journal contains a redacted-but-not-purged secret.
- A `commands/*.json` sidecar records an environment variable not on `redaction.environment_allowlist`.
