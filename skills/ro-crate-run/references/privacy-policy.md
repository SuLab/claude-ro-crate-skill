# Privacy Policy

## Default Privacy Table (SPEC §13.1)

| Data class              | Default       | Override via config                    |
|-------------------------|---------------|----------------------------------------|
| Command stdout/stderr   | private       | `privacy.capture_stdout`               |
| Environment variables   | private       | `privacy.env_allowlist`                |
| File contents           | not captured  | `file_policy.*`                        |
| Git diff                | not captured  | `file_policy.include_git_diff`         |
| Declared inputs/outputs | private       | `privacy.public_by_default`            |
| Event journal           | private       | `finalize --include-event-journal`     |
| Crate metadata          | public        | (always public)                        |

## Redaction Rules (SPEC §13.2)

- **Before persistence:** sensitive fields are redacted from event payloads before they are written to the journal (redact-before-append).
- **Allowlist env capture:** only environment variable names on `privacy.env_allowlist` are captured; others are dropped.
- **Denylist names:** any payload key matching `privacy.redact_fields` is replaced with `"[REDACTED]"`.
- **Regex patterns:** values matching `redaction.patterns_file` regexes are replaced inline.
- **Never read:** `.env` files, OS keychains, SSH keys (`~/.ssh/`), cloud credential files (`~/.aws/`, `~/.gcp/`, `~/.azure/`) are never captured regardless of config.

## Redaction Journal

When redaction is applied with `rcr redact --apply`:
- The original journal is preserved as `events.ndjson.pre-redact`.
- Redacted events are replaced with tombstone events carrying `event_type: "run.redaction.completed"`.
- The replacement journal must pass Level-0 integrity check before the original is overwritten.

## Public Export Gate (SPEC §13.4)

The `finalize --public` command runs Level-5 validation AFTER staging all files (including any embedded event journal). Export is blocked when:

1. Any staged event payload or file contains a secret-pattern match.
2. A denylist filename is present in the staged tree.
3. An environment variable not on the allowlist appears in the journal.
4. Any `redacted: true` event is included without the redaction having been applied.
5. `privacy.require_privacy_gate` is true and the gate check was not run.

On gate failure, the staged tree is discarded and a `run.export.blocked` event is emitted.

## Sensitive File Patterns (never captured)

- `.env`, `.env.*`, `*.env`
- `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `*.p12`, `*.pfx`
- `~/.ssh/**`, `~/.aws/**`, `~/.gcp/**`, `~/.azure/**`
- `*credentials*`, `*secret*`, `*token*` (filename matching, case-insensitive)
- Any file listed in `.gitignore` with a `!` exception is still subject to denylist check.
