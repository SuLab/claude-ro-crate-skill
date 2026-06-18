---
name: RO-Crate Run
description: Capture, checkpoint, validate, and finalize RO-Crate provenance for Claude Code sessions, command-line executions, file edits, generated outputs, workflow runs, Process Run Crate, Workflow Run Crate, and Provenance Run Crate metadata.
allowed-tools: Bash(rcr *) Bash(git status) Bash(git rev-parse *) Bash(git diff *) Read Write Edit
---

# RO-Crate Run

Route invocations to the bundled CLI:

```bash
${CLAUDE_SKILL_DIR}/scripts/rcr $ARGUMENTS
```

## §8.2 Operating rules

1. **Start/resume first.** Before any provenance-relevant work run `rcr start` or `rcr resume`.
2. **Route invocations.** Pass the full argument string to `${CLAUDE_SKILL_DIR}/scripts/rcr`.
3. **Use `rcr run --` for substantive commands.** Never run significant commands outside `rcr run`.
4. **Declare inputs and outputs.** Use `rcr input` / `rcr output` for important files.
5. **Record decisions.** Capture human choices with `rcr note` (observations) or `rcr decision` (rationale with optional `--rationale`).
6. **Use `rcr phase` / `rcr step` for structured workflows.** Wrap long or multi-stage work with `rcr phase <name>` and `rcr step start/end <id>` so provenance reflects structure.
7. **Check status before final answers.** Run `rcr status` before delivering results when a run is active.
8. **Checkpoint regularly.** Checkpoint after each major phase and always before finalization.
9. **Never invent facts.** Do not fabricate execution times, file hashes, or command output.
10. **Mark inferred metadata.** Set `inferred=true` in event payloads for derived or estimated values.
11. **Prefer Process Run Crate.** Default to `--profile process` unless a formal workflow definition file exists.
12. **Promote to Provenance Run Crate only with evidence.** Require step-level execution evidence before selecting the provenance profile.
13. **Hook-captured events are observed facts.** Do not override or re-emit events already recorded by hooks.
14. **User-declared metadata are declarations, not observations.** Metadata provided by the user (paths, roles, descriptions) must be recorded as declared, not inferred.
15. **Ask for missing metadata only when necessary.** Prompt the user only when metadata is required for profile validity, a privacy decision, or meaningful reproducibility — not proactively.

## Reference documents

Load these only when needed:

- Mapping rules: `references/mapping-policy.md`
- Profile selection: `references/profile-selection.md`
- Validation: `references/validation-rules.md`
- Privacy: `references/privacy-policy.md`
