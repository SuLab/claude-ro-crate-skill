# Changelog

## Unreleased

### Fixed
- Redaction now masks structured (dict) payloads by sensitive key name, not only
  by value pattern — closing a fail-open path that let `{"password": ...}` reach
  the immutable journal in cleartext.
- `export_zip` stores entries with `ZIP_DEFLATED` (they were shipping
  uncompressed because per-entry `ZipInfo` defaults to `ZIP_STORED`).
- Recovery rewrites `events.ndjson` atomically (temp file + `replace`) so a crash
  mid-repair can no longer truncate the authoritative journal.
- Imported RO-Crate Actions now materialize: the importer emits a paired
  `execution.command.started` and the reducer create-or-updates the record.
- Tool decisions are minted as `#tool-decision/{seq}`, disjoint from human
  `#decision/{idx}`, ending a silent same-`@id` entity merge.
- The public-export privacy gate now applies user-configured custom redaction
  patterns to the in-memory metadata scan, not only the file scan.
- `signing` and SHACL degrade cleanly: `mypy --strict` passes with and without
  the optional `cryptography`/`pyshacl` extras.

### Changed
- Audit-driven architecture refactor (extensibility, modularity, DRY, clean code),
  behavior- and byte-preserving (golden crates unchanged):
  - Profile facts unified in a `ProfileSpec`/`PROFILES` registry; `RunModel`
    agent-activity fields grouped into an `AgentActivity` sub-dataclass; event
    projection driven by a `_PROJECTORS` registry instead of a 29-branch ladder.
  - `write_crate`, `CommandRunner.run`, and `export.finalize` decomposed; event
    aggregation moved out of the mapping builders into the reducer (builders are
    pure 1:1 mappers again).
  - Workflow-engine detection routed through `adapters.engine_for_path`/
    `is_workflow_definition`; validation finding severity made a structural field;
    `EventWriter.rewrite_chain` / `events.verify_hash_chain` single-source the
    full-chain rewrite and chain check.
  - Shared helpers single-sourced: `mapping/_helpers` node constructors
    (`ref`/`property_value`/`sha256_identifier`/`fragment_id`/`root_ref`),
    `fs.bare_sha256`/`write_json`, `BYTES_PER_MB`, terminal-event frozensets,
    `EVENT_SCHEMA_VERSION`/`SIDECAR_SCHEMA_VERSION`/`EXISTENCE_VALUES`/
    `DEFAULT_ENV_ALLOWLIST`/`ROOT_DATASET_ID` constants.
- Earlier refactor: shared helpers in `constants.py`/`ids.py`/`events.py`/
  `redaction.py`; generic dataclass (de)serialization; validation `CHECKS`
  registry + `graphview` + cached entity index; adapter `WorkflowAdapter` protocol
  + homepage registry; argparse `set_defaults` dispatch.
- `materialize/mapping.py` split into a `materialize/mapping/` package; installer
  extracted into `install.py`; domain helpers extracted from `commands.py` into
  `oci.py`/`software_probe.py`; per-event hook wrappers collapsed into one generic
  `rocrate_hook.py`; the eight dead per-command `rocrate_*.py` wrappers removed;
  root `files.py` renamed to `fs.py`.
- Added guard tests: asset byte-identity (`test_asset_sync`), hook-event sync,
  recommendation-code coverage.
- Comment hygiene: removed internal milestone/phase markers and fix-history; added
  module and entry-point docstrings throughout.

## 0.1.0

- Initial implementation of the Claude Code RO-Crate provenance plugin and CLI.
