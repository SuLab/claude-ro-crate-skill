---
name: RO-Crate Run Admin
description: User-invoked administrative RO-Crate Run operations that are destructive or release-affecting — applying redaction in place, public finalization/export, and signing. Not model-invocable.
disable-model-invocation: true
allowed-tools: Bash(rcr *)
---

# RO-Crate Run Admin

These operations change or release provenance irreversibly and MUST be run explicitly by a human, never auto-invoked by the model.

Route invocations to the bundled CLI:

```bash
${CLAUDE_SKILL_DIR}/scripts/rcr $ARGUMENTS
```

Supported admin operations:

- `rcr redact --apply` — rewrite the event journal with redactions applied (preserves a pre-redaction copy of the journal).
- `rcr finalize --public` — run the public privacy gate and produce a release package; fails closed on any leak.
- `rcr sign` — sign the finalized crate manifest with the project Ed25519 key.

Before any of these, confirm intent with the human and run `rcr validate --strict` first.
