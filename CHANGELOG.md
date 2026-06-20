# Changelog

## Unreleased

### Fixed
- Tool decisions are minted as `#tool-decision/{seq}`, disjoint from human
  `#decision/{idx}`, ending a silent same-`@id` entity merge.
- The public-export privacy gate now applies user-configured custom redaction
  patterns to the in-memory metadata scan, not only the file scan.
- `signing` and SHACL degrade cleanly: `mypy --strict` passes with and without
  the optional `cryptography`/`pyshacl` extras.

### Changed
- Architecture refactor for extensibility, modularity, DRY, and clean code:
  shared helpers centralized in `constants.py`/`ids.py`/`events.py`/`redaction.py`;
  generic dataclass (de)serialization (no per-type registration); validation
  `CHECKS` registry + `graphview` helpers + cached entity index; adapter
  `WorkflowAdapter` protocol + homepage registry; argparse `set_defaults` dispatch.
- `materialize/mapping.py` split into a `materialize/mapping/` package; installer
  extracted from `commands.py` into `install.py`; the per-event hook wrappers
  collapsed into one generic `rocrate_hook.py`; root `files.py` renamed to `fs.py`.
- Comment hygiene: removed internal milestone/phase markers and fix-history; added
  module and entry-point docstrings throughout.

## 0.1.0

- Initial implementation of the Claude Code RO-Crate provenance plugin and CLI.
