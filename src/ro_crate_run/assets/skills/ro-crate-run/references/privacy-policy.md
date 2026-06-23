# Privacy Policy

## Default Privacy Table (SPEC §13.2)

| Data class              | Default       | Override via config                    |
|-------------------------|---------------|----------------------------------------|
| Command stdout/stderr   | private       | `privacy.include_full_logs`            |
| Environment variables   | private       | `redaction.environment_allowlist`      |
| File contents           | not captured  | `file_policy.*`                        |
| Git diff                | not captured  | `file_policy.include_git_diff`         |
| Declared inputs/outputs | private       | `privacy.public_by_default`            |
| Event journal           | private       | `finalize --include-event-journal`     |
| Crate metadata          | public        | (always public)                        |

## Redaction Rules (SPEC §13.3)

- **Before persistence:** sensitive fields are redacted from event payloads before they are written to the journal (redact-before-append).
- **Allowlist env capture:** only environment variable names on `redaction.environment_allowlist` are captured; others are dropped.
- **Secret values:** values matching the built-in secret regexes (and `KEY=value` assignments whose key contains TOKEN/SECRET/PASSWORD/etc.) are replaced with `[REDACTED:secret]`.
- **Regex patterns:** values matching the built-in secret regexes plus any extra regexes from `redaction.patterns_file` are replaced inline with `[REDACTED:secret]`.
- **Never read:** files whose basename matches a sensitive pattern — `.env` files, SSH private keys (`id_rsa`/`id_ed25519`), and credential files (`*credentials*`, e.g. an AWS `credentials` file) — are never captured regardless of config; OS keychains and files outside the project root are never read.

## Redaction Journal

When redaction is applied with `rcr redact --apply`:
- The original journal is preserved as a timestamped backup (`events.ndjson.pre-redaction-<timestamp>`).
- Events are rewritten in place: matched values are replaced, changed events are marked `redacted: true`, and the whole hash chain is recomputed.
- A `redaction.applied` event is appended recording the finding count and the path of the redacted-journal report.

## Public Export Gate (SPEC §13.4)

The `finalize --public` command runs Level-5 validation AFTER staging all files (including any embedded event journal). Export is blocked when:

1. Any staged event payload or file contains a secret-pattern match.
2. A `commands/*.json` sidecar records an environment variable not on `redaction.environment_allowlist`.

The L5 gate only runs when `validation.require_privacy_gate` is true (the default); setting it false skips the gate entirely.

On gate failure, the staged tree is discarded and a `run.export.blocked` event is emitted.

## Sensitive File Patterns (never captured)

- `.env`, `.env.*`, `*.env`
- `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `*.p12`, `*.pfx`
- `*credentials*`, `*secret*`, `*token*`

Matching is against the file's basename only (lowercased), not its path: a file inside `~/.ssh`, `~/.aws`, etc. is excluded only if its basename matches one of these globs (e.g. a file named `credentials` or `id_rsa`).
