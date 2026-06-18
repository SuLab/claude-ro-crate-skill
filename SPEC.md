# Engineering Specification: Claude Code RO-Crate Provenance Skill

**Document version:** 1.2 revised specification  
**Prepared:** 2026-06-17  
**Revision 1.2 (2026-06-17):** Corrected RO-Crate 1.2 Root Data Entity requirements for `name`, `description`, and `license`; clarified project/personal skill invocation versus namespaced plugin invocation; added required plugin `hooks/hooks.json`; removed `${CLAUDE_SKILL_DIR}` from recommended `allowed-tools`; clarified checkpoint staleness, command-start journaling, event-writer recovery, public source/diff defaults, root `conformsTo`, JSON-LD null handling, and current RO-Crate reference URLs.  
**Revision 1.1 (2026-06-17):** Aligned command-action log/sidecar linking with the Workflow Run Crate convention (schema.org `about` on the `File`, not `workPerformed`); removed the non-existent `show-in-discovery` skill frontmatter field; clarified that `${CLAUDE_SKILL_DIR}` is a `SKILL.md` content substitution only, and that hooks and the CLI must resolve paths via `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PROJECT_DIR` or script-relative lookup; flagged `${CLAUDE_SKILL_DIR}` expansion inside `allowed-tools` frontmatter as unverified.  

**Short name / command directory:** `ro-crate-run`  
**Primary deliverable:** Claude Code skill plus provenance CLI, hooks, materializer, validator, and reference documentation  
**Primary output:** RO-Crate directory and optional ZIP archive containing run metadata, selected artifacts, logs, validation reports, and reproducibility evidence  
**Default RO-Crate version:** RO-Crate 1.2  
**Run profile targets:** Process Run Crate 0.5, Workflow Run Crate 0.5, Provenance Run Crate 0.5  
**Primary Python library:** `rocrate` / `ro-crate-py` 0.15.x or newer compatible 0.x release, pinned by the implementation

---

## 1. Purpose

This document replaces the earlier draft engineering specification for a Claude Code skill that captures, validates, and materializes provenance as RO-Crate. It has two objectives:

1. Provide a critical analysis of the draft specification and identify corrections required for current RO-Crate, Workflow Run RO-Crate, ro-crate-py, and Claude Code reality.
2. Define a revised comprehensive engineering specification for implementation.

The core product remains a layered provenance system, not a prompt-only instruction set. Claude Code can interpret, summarize, label phases, and ask for missing metadata, but deterministic scripts and hooks are responsible for recording facts, hashing files, writing state, and materializing JSON-LD.

---

## 2. Critical analysis of the attached draft

### 2.1 What the draft gets right

The draft's central architecture is sound. A provenance system for Claude Code should not depend on the model remembering to write metadata. The proposed layers--Claude Code skill, hooks, wrapper CLI, append-only event journal, ro-crate-py materializer, and validator--are the right separation of concerns.

The draft also correctly identifies the important provenance gap in human-in-the-loop agentic coding: Claude Code can edit files and run commands, but humans may also run terminal commands outside the session. A wrapper CLI is therefore required for manual terminal capture.

The default-to-Process-Run-Crate policy applies to ad hoc, single-command activity. Because the actions taken by the agent themselves constitute the workflow (§16), structured agent work — multiple commands or declared phases — is promoted to Workflow Run Crate (synthesizing the workflow from those actions when no external definition file exists), and runs with step-level execution evidence are promoted to Provenance Run Crate.

### 2.2 Required corrections

| Area | Draft issue | Correction in this specification |
|---|---|---|
| RO-Crate version | The draft leaves open whether to use RO-Crate 1.2 or older WRROC examples. | Use RO-Crate 1.2 as the default base metadata specification. Maintain compatibility with WRROC 0.5, which still references RO-Crate 1.1 in its profile pages. |
| Metadata descriptor | The draft treats descriptor `conformsTo` and root profile conformance too loosely. | `ro-crate-metadata.json` MUST conform to the RO-Crate 1.2 base spec. Profile conformance MUST be declared on the Root Data Entity in RO-Crate 1.2 style. |
| Root Data Entity fields | The draft says root requires `dateCreated` and `dateModified`. | RO-Crate 1.2 requires a Root Data Entity with an `@id`; root properties MUST include `@type: Dataset`, `name`, `description`, `datePublished`, and `license`. `dateCreated` and `dateModified` MAY be added as run facts. |
| Profile URIs | The draft names profiles but does not pin current URI versions. | Use `https://w3id.org/ro/wfrun/process/0.5`, `https://w3id.org/ro/wfrun/workflow/0.5`, and `https://w3id.org/ro/wfrun/provenance/0.5`. |
| Workflow-run context | The draft uses WRROC terms such as `environment`, `resourceUsage`, `containerImage`, and `ParameterConnection` without requiring the context. | When using non-base RO-Crate workflow-run terms, include `https://w3id.org/ro/terms/workflow-run/context` or use full URIs. |
| Claude Code skills | The draft implies the YAML `name` determines the slash command. | In Claude Code, project/personal skill commands are derived from the skill directory path. Plugin skills under `skills/` are namespaced by plugin, for example `/PLUGIN_NAMESPACE:ro-crate-run`. The YAML `name` is a display label except where Claude Code explicitly documents plugin-root single-skill behavior. |
| Claude Code skill command interface | The draft lists subcommands like `/ro-crate-run start`, but does not specify argument handling. | Project/personal use is `/ro-crate-run ...`; plugin use is `/PLUGIN_NAMESPACE:ro-crate-run ...`; `SKILL.md` MUST route `$ARGUMENTS` to `rcr <subcommand>`. Direct CLI use remains `rcr start`, `rcr run --`, etc. |
| Skill scope | The draft mentions project-level or plugin-level hooks but under-specifies distribution. | For reusable distribution, implement as a Claude Code plugin. For a single project, install under `.claude/`. Standalone skill files are not enough for always-on capture. |
| Hooks | The draft omits important current hook events. | Add optional support for `PermissionRequest`, `PermissionDenied`, `StopFailure`, `CwdChanged`, `WorktreeCreate`, `WorktreeRemove`, `PreCompact`, `PostCompact`, `TaskCreated`, `TaskCompleted`, `SubagentStart`, and `SubagentStop`. |
| Hook input model | The draft does not specify that hooks must read JSON context. | Hook scripts MUST consume Claude Code hook JSON from stdin and treat environment variables only as supplemental. |
| Provenance Run selection | The draft references `rcr step` in profile-selection examples but does not define the command. | Add explicit `rcr step start`, `rcr step end`, and `rcr run --step <id> -- ...`. Provenance Run requires step/action evidence, not merely phase labels. |
| Command mapping | The draft maps each command to `CreateAction`. | Use `CreateAction` when outputs are produced; `UpdateAction` for in-place modification; `Action` or `ActivateAction` for non-creating commands. Include `actionStatus`, and `error` for failures. |
| Command line storage | The draft recommends storing exact command in `description`. | WRROC states command-line descriptions are not directly re-executable. Store a structured invocation sidecar JSON file and use `description` only for readable summary. |
| Prompts | The draft captures prompts but leaves public inclusion unresolved. | Raw prompts are private by default. Public crates include curated notes, decisions, and summaries unless `privacy.include_prompts=true` is explicitly configured. |
| Event journal inclusion | The draft leaves open whether to include the journal in the crate. | The event journal is private by default and excluded from public RO-Crate unless redacted and explicitly enabled. Include a derived public run summary and validation report by default. |
| Logs | The draft does not settle whether logs are copied or referenced. | Logs are captured as files, redacted, size-limited, and included or referenced according to policy. Do not inline full logs in JSON-LD. |
| IDs | The draft proposes deterministic IDs like `#cmd/<event_id>`. | Keep stable internal event IDs; generate WRROC action IDs as stored UUID/URN identifiers and persist the mapping in state for deterministic rebuild. |
| Validation | The draft assumes profile validation but does not address lack of a universal WRROC validator. | Implement layered validation: event JSON Schema/Pydantic, state checks, RO-Crate structural checks, JSON-LD expansion, and custom WRROC 0.5 profile rules. Optionally add SHACL or JSON Schema profile checks. |
| ro-crate-py dependency | The draft names ro-crate-py but does not pin versions. | Pin and test `rocrate>=0.15,<0.16` initially, or a later compatible range after integration testing. Require Python 3.9+. |
| Security | The draft uses denylist-based redaction. | Use allowlist capture for environment variables, plus denylist and regex redaction. Redact before persistence where possible; record redaction provenance without preserving secrets. |
| Tamper evidence | The draft lists signing/hash chaining as later hardening. | Add event hash chaining in v1 as tamper-evident metadata. Do not claim tamper-proof guarantees without external controls. |

### 2.3 Design questions resolved

1. **Should Claude Code file edits be represented as provenance actions?**  
   Represent significant source/output changes as `UpdateAction` or `CreateAction` only when they are relevant to the deliverable. Preserve detailed edit facts in the private event journal. Avoid polluting public crate metadata with every small edit.

2. **Should prompts be included in the final crate by default?**  
   No. Store redacted prompts in the private event journal if configured. Public crates include curated notes, decisions, and summaries only.

3. **Should the event journal itself be included in the RO-Crate?**  
   No by default. Include only after redaction and explicit configuration. Include `run-summary.json`, `validation-report.json`, selected logs, and manifest by default.

4. **Should stdout/stderr logs always be included?**  
   No. Capture logs to files; redact and include or reference them according to size and privacy policy. Link logs to actions with `about` where appropriate.

5. **Minimum metadata for finalized status:**  
   A finalized run must have valid base RO-Crate metadata, root profile conformance, at least one action or declared no-op rationale, actor/software metadata, selected inputs/outputs, validation report, and no critical privacy validation failures.

6. **Should failed commands be represented?**  
   Yes when they are relevant to the computational history. Represent failed actions with `actionStatus` failed and `error`, and link logs. Not every transient inspection failure needs a public action.

7. **Native imports from exporters?**  
   Support as adapters after the core event-journal-to-crate path. Native exporters from workflow systems should be preferred when they provide richer provenance.

8. **RO-Crate 1.2 vs WRROC examples:**  
   Use RO-Crate 1.2 base metadata. Use current WRROC 0.5 profile URIs and workflow-run context. Maintain tests against profile examples because WRROC profile pages still extend RO-Crate 1.1.

---

## 3. Normative basis and compatibility stance

### 3.1 Base metadata standard

The implementation MUST generate RO-Crate Metadata Specification 1.2 by default. The metadata descriptor entity for `ro-crate-metadata.json` MUST conform to the RO-Crate 1.2 base specification, and the Root Data Entity MUST declare profile conformance for Process, Workflow, or Provenance Run Crate.

### 3.2 Run profile standard

The implementation targets the current Workflow Run RO-Crate profile collection:

- Process Run Crate 0.5: `https://w3id.org/ro/wfrun/process/0.5`
- Workflow Run Crate 0.5: `https://w3id.org/ro/wfrun/workflow/0.5`
- Provenance Run Crate 0.5: `https://w3id.org/ro/wfrun/provenance/0.5`

WRROC 0.5 profile pages state they extend RO-Crate 1.1, while RO-Crate 1.2 is now the current base recommendation. Therefore, the implementation MUST maintain a compatibility test suite that checks both:

1. RO-Crate 1.2 structural correctness.
2. WRROC 0.5 profile expectations and examples.

Some WRROC profile pages retain historical example snippets with older profile URIs. Golden tests MAY use those examples for relationship patterns, but they MUST normalize or reject stale `conformsTo` profile URIs and assert the 0.5 URIs listed above.

### 3.3 Claude Code platform basis

The implementation assumes current Claude Code skill and hook semantics:

- Skills live in project, personal, or plugin locations.
- A skill directory contains `SKILL.md` and optional supporting files.
- Project/personal slash command names are derived from skill directory names; plugin skill commands are namespaced by plugin when installed under a plugin `skills/` directory.
- Skills can define allowed tools, shell context, hooks, paths, and invocation controls in frontmatter.
- Hooks are configured lifecycle handlers that receive JSON context and may observe, block, or modify behavior according to Claude Code's documented hook contract.
- Project-level hooks are suitable for one repository; plugins are suitable for reusable distribution.

---

## 4. Product definition

### 4.1 Product name

**Claude Code RO-Crate Provenance Skill**

### 4.2 Skill command names

Project or personal skill invocation:

```text
/ro-crate-run
```

For project or personal skills, the command name MUST be derived from the skill directory name:

```text
.claude/skills/ro-crate-run/SKILL.md
```

For plugin distribution under the plugin `skills/` directory, the command is namespaced by plugin. Documentation and examples for released plugins MUST use the concrete namespace from `.claude-plugin/plugin.json`, for example:

```text
/ro-crate-run:ro-crate-run
```

when the plugin namespace is `ro-crate-run`.

The plugin skill path is:

```text
skills/ro-crate-run/SKILL.md
```

The rest of this specification uses `/ro-crate-run` in examples for readability; plugin release documentation MUST translate examples to the namespaced command.

### 4.3 CLI name

`rcr`

The skill invokes `rcr` internally, and users may invoke `rcr` directly in a terminal.

### 4.4 Primary users

- Researchers and engineers using Claude Code for computational work.
- Data scientists using Claude Code for human-in-the-loop analysis.
- Workflow developers using Claude Code to run, debug, or modify workflows.
- Reproducibility reviewers who need a structured crate documenting what happened.

### 4.5 Success criteria

The implementation is successful when:

1. A Claude Code session can start or resume provenance capture with one skill invocation.
2. Claude Code tool activity, relevant commands, file changes, declared inputs, outputs, notes, decisions, and validation events are captured in an append-only event journal.
3. Human terminal commands can be captured through `rcr run --`.
4. The crate can be regenerated deterministically from the event journal plus state mapping.
5. The generated RO-Crate conforms structurally to RO-Crate 1.2 and, where applicable, WRROC 0.5 profile requirements.
6. Sensitive prompts, secrets, and environment details are not exposed in public crates by default.
7. The skill can block or warn before completion in monitored/enforced modes when provenance is stale or invalid.
8. The implementation documents all known limitations in a final summary.

---

## 5. Non-goals

The first production release does not need to:

1. Fully infer dataflow dependencies from arbitrary shell commands.
2. Observe human terminal commands not run through `rcr` or an explicit shell integration.
3. Replace native provenance exporters for workflow management systems.
4. Guarantee tamper-proof provenance without external signing, append-only storage, attestation, or controlled CI finalization.
5. Capture full dataset contents or full unrestricted environments.
6. Provide an interactive graphical RO-Crate editor.
7. Upload crates to repositories or registries, although export integrations may be added later.
8. Automatically certify scientific reproducibility; it records evidence and validates metadata structure, not truth.

---

## 6. Distribution models

### 6.1 Project-local distribution

Use this for a single repository:

```text
.claude/
  skills/
    ro-crate-run/
      SKILL.md
      references/
        mapping-policy.md
        profile-selection.md
        validation-rules.md
        privacy-policy.md
      scripts/
        rcr
        rocrate_start.py
        rocrate_event.py
        rocrate_run.py
        rocrate_checkpoint.py
        rocrate_validate.py
        rocrate_finalize.py
        rocrate_redact.py
        rocrate_inspect.py
      examples/
        process-run-crate/
        workflow-run-crate/
        provenance-run-crate/
  hooks/
    rocrate_hook.py
    rocrate_session_start.py
    rocrate_user_prompt.py
    rocrate_pre_tool_use.py
    rocrate_post_tool_use.py
    rocrate_post_tool_failure.py
    rocrate_permission.py
    rocrate_post_tool_batch.py
    rocrate_cwd_changed.py
    rocrate_worktree.py
    rocrate_task.py
    rocrate_compact.py
    rocrate_stop.py
    rocrate_stop_failure.py
    rocrate_session_end.py
  settings.json
```

### 6.2 Plugin distribution

Use this for reusable distribution across projects and teams:

```text
ro-crate-run-plugin/
  .claude-plugin/
    plugin.json
  skills/
    ro-crate-run/
      SKILL.md
      references/
      scripts/
      examples/
  hooks/
    hooks.json
    rocrate_hook.py
    ...
  templates/
    settings.rocrate.json
  README.md
  CHANGELOG.md
  LICENSE
```

Plugin distribution is preferred for versioned release because it can package skills, hooks, scripts, and configuration templates together.

The plugin manifest MUST declare the plugin namespace used by slash commands, and `hooks/hooks.json` MUST register every plugin hook command and matcher. Hook scripts in the tree are not sufficient by themselves; Claude Code only invokes plugin hooks that are declared in the hook manifest.

### 6.3 Runtime state directory

Each project using the skill has a runtime state directory:

```text
.ro-crate-run/
  config.json
  state.json
  events.ndjson
  lock
  id-map.json
  secrets-redaction.json
  logs/
  commands/
  hashes/
  snapshots/
  staging/
  reports/
  ro-crate/
    ro-crate-metadata.json
    run-summary.json
    validation-report.json
```

`events.ndjson` is the source event stream. `id-map.json` maps stable event IDs to RO-Crate entity IDs so rebuilds are deterministic while entity identifiers can follow WRROC UUID-style expectations.

---

## 7. Operating modes

### 7.1 Advisory mode

Advisory mode records events and emits warnings but does not block Claude Code actions or completion.

Use cases:

- Early experimentation.
- Low-risk projects.
- Initial adoption.

Behavior:

- Hooks append events when configured.
- `rcr status` and `rcr validate` report issues.
- Stop hook never blocks.
- Raw Bash commands are allowed, but warnings encourage `rcr run --`.

### 7.2 Monitored mode

Monitored mode records events and blocks only high-risk completion states.

Use cases:

- Research or engineering work where the crate is important but not the only deliverable.
- Mixed Claude/human workflows.

Behavior:

- Hooks capture prompts, tool activity, file edits, command activity, permission events, and failures.
- Stop hook attempts checkpoint if stale.
- Stop hook blocks only when materialization fails, required metadata is missing, or privacy validation fails.
- Raw Bash commands generate warnings unless policy marks them risky.

### 7.3 Enforced mode

Enforced mode treats provenance as a deliverable.

Use cases:

- Reproducibility packages.
- Regulated or audited analysis.
- CI-gated workflows.

Behavior:

- Substantive Bash commands MUST use `rcr run --` unless allowlisted.
- Declared required outputs MUST exist at finalization.
- The crate MUST validate before final response/finalization.
- Stop hook blocks stale or invalid provenance using Claude Code's documented blocking hook mechanism.
- CI fails on stale event journals, validation errors, and policy violations.

---

## 8. Claude Code skill design

### 8.1 `SKILL.md` frontmatter

`SKILL.md` MUST be concise and SHOULD stay below 500 lines. Detailed mapping and validation rules belong in reference files.

Recommended project skill frontmatter:

```yaml
---
name: RO-Crate Run
description: Capture, checkpoint, validate, and finalize RO-Crate provenance for Claude Code sessions, command-line executions, human-in-the-loop analysis, file edits, generated outputs, workflow runs, Process Run Crate, Workflow Run Crate, and Provenance Run Crate metadata. Use when a user asks to create or maintain an RO-Crate, record reproducible provenance, run commands with provenance, validate a crate, or finalize a run package.
allowed-tools: Bash(/absolute/path/to/.claude/skills/ro-crate-run/scripts/rcr *) Bash(python3 /absolute/path/to/.claude/skills/ro-crate-run/scripts/*) Bash(git status) Bash(git rev-parse *) Bash(git diff *) Read Write Edit
---
```

> **Frontmatter notes (verified against current Claude Code skills documentation):**
> - There is no `show-in-discovery` field; it has been removed. A project/personal skill is discoverable by default (`user-invocable: true`, with its `description` always in context), so no field is required to make `/ro-crate-run` visible. Use `user-invocable: false` only to *hide* a skill from the `/` menu. Plugin skills are shown under their plugin namespace.
> - The `allowed-tools` `Bash(... *)` pattern form is supported and documented. `${CLAUDE_SKILL_DIR}` is documented as a substitution for skill **content**, not for the `allowed-tools` frontmatter value. Installers MUST render this frontmatter with literal resolved command paths or documented PATH-based commands; they MUST NOT leave `${CLAUDE_SKILL_DIR}` in `allowed-tools`.

For highly controlled deployments, create a second administrative skill or command that uses:

```yaml
disable-model-invocation: true
```

for operations that must be user-invoked explicitly, such as destructive redaction, final export, or CI policy changes.

### 8.2 Skill body requirements

The body of `SKILL.md` MUST instruct Claude to:

1. Start or resume an `rcr` run before provenance-relevant work.
2. Route `/ro-crate-run <subcommand>` or `/PLUGIN_NAMESPACE:ro-crate-run <subcommand>` to `${CLAUDE_SKILL_DIR}/scripts/rcr <subcommand>`.
3. Use `rcr run --` for substantive commands.
4. Declare important inputs and outputs.
5. Record human decisions with `rcr note` or `rcr decision`.
6. Use `rcr phase` and `rcr step` for long or structured workflows.
7. Check `rcr status` before final answers when a run is active.
8. Checkpoint after major phases and before finalization.
9. Never invent execution facts.
10. Mark inferred metadata as inferred in event payloads.
11. The agent's actions are the workflow: use Process Run Crate for single, flat command runs; structured work (multiple commands or phases) is a Workflow Run Crate, synthesizing the workflow from the agent's actions when no external definition file exists.
12. Promote to Provenance Run Crate only with step-level execution evidence.
13. Treat hook-captured events as observed facts.
14. Treat user-declared metadata as declarations, not observations.
15. Ask for missing metadata only when needed for profile validity, privacy decisions, or meaningful reproducibility.

### 8.3 Skill invocation routing

The project/personal skill MUST support these invocations. Plugin release documentation MUST replace `/ro-crate-run` with the concrete namespaced command:

```text
/ro-crate-run start "Evaluate model variants"
/ro-crate-run status
/ro-crate-run input data/raw.csv --role primary-dataset
/ro-crate-run output results/report.md --required
/ro-crate-run note "Excluded rows missing labels."
/ro-crate-run phase preprocessing
/ro-crate-run step start normalize
/ro-crate-run run -- python scripts/evaluate.py
/ro-crate-run checkpoint
/ro-crate-run validate
/ro-crate-run finalize --zip
/ro-crate-run resume
```

Claude Code passes arguments to the skill. The skill body MUST route the full argument string to `rcr`. Direct CLI invocation uses the same subcommands without the slash prefix.

---

## 9. CLI specification

### 9.1 CLI executable

The CLI executable is:

```text
${CLAUDE_SKILL_DIR}/scripts/rcr
```

It MUST be a thin dispatcher to Python modules. It MUST work when called from Claude Code and from a human terminal.

`${CLAUDE_SKILL_DIR}` is only resolved as a substitution inside `SKILL.md` content (for example, the routing instruction in §8.2). It is **not** exported to hook subprocesses or to a human terminal. Hooks and direct terminal use MUST resolve the script location via `CLAUDE_PLUGIN_ROOT` (plugin distribution) or `CLAUDE_PROJECT_DIR` (project distribution), falling back to locating the skill directory relative to the script's own path (see §20.3).

### 9.2 Commands

```text
rcr start [TITLE] [--mode advisory|monitored|enforced] [--profile process|workflow|provenance|auto]
rcr resume
rcr status [--json]
rcr note TEXT [--public|--private]
rcr decision TEXT [--rationale TEXT] [--public|--private]
rcr phase NAME [--complete-current]
rcr phase complete [NAME]
rcr step start STEP_ID_OR_NAME [--workflow-step ID] [--description TEXT]
rcr step end STEP_ID_OR_NAME [--status completed|failed|skipped]
rcr input PATH_OR_URI [--role ROLE] [--description TEXT] [--required] [--copy|--reference]
rcr output PATH_OR_URI [--role ROLE] [--description TEXT] [--required] [--copy|--reference]
rcr parameter NAME VALUE [--formal-parameter ID] [--type TYPE]
rcr software COMMAND_OR_NAME [--version VERSION] [--type TYPE]
rcr run [--step STEP] [--inputs PATHS] [--outputs PATHS] -- COMMAND [ARGS...]
rcr checkpoint [--profile process|workflow|provenance|auto]
rcr validate [--strict] [--json]
rcr finalize [--zip] [--include-event-journal] [--public|--private]
rcr inspect [--events] [--crate] [--graph]
rcr redact [--dry-run] [--apply] [--policy FILE]
rcr export [--zip] [--out PATH]
rcr hash PATH_OR_URI
```

### 9.3 `rcr start`

`rcr start` MUST:

1. Create `.ro-crate-run/` and required subdirectories.
2. Create `config.json` from defaults and user flags.
3. Create `state.json`, `id-map.json`, and `events.ndjson` if absent.
4. Generate `run_id` and initial `session_id` if available.
5. Record title, cwd, project root, Git repository state, Claude Code session metadata, skill version, CLI version, Python version, rocrate package version, OS summary, and configured privacy policy.
6. Append `run.started` and `environment.observed` events.
7. Perform an initial checkpoint unless `--no-checkpoint` is provided.

### 9.4 `rcr resume`

`rcr resume` MUST:

1. Load `state.json`.
2. Validate journal readability.
3. Append `run.resumed`.
4. Check stale status.
5. Report current profile, event count, last checkpoint, and validation state.

### 9.5 `rcr status`

`rcr status` MUST show:

- Run ID.
- Mode.
- Selected or pending profile.
- Current phase and step.
- Event count.
- Last checkpoint sequence and timestamp.
- Dirty/stale state.
- Declared inputs and outputs.
- Missing required metadata.
- Privacy warnings.
- Validation result.

### 9.6 `rcr note` and `rcr decision`

Notes and decisions MUST be captured as separate event types.

- `note` records contextual information.
- `decision` records a choice, rationale, and alternatives if known.

Both commands support public/private visibility. Private notes remain in the private event journal. Public notes may be represented in the crate as `CreativeWork` or linked contextual entities.

### 9.7 `rcr phase` and `rcr step`

A phase is a human-friendly grouping. A step is a prospective or retrospective computational unit that may map to a workflow step.

Rules:

- A phase MAY contain multiple steps.
- A step MAY map to a WRROC `HowToStep` and step-level `CreateAction`.
- A phase alone MUST NOT cause profile promotion to Provenance Run Crate.
- Provenance Run Crate promotion requires step-level actions and enough mapping evidence.

### 9.8 `rcr input`, `rcr output`, and `rcr parameter`

Input/output declarations MUST record:

- Path or URI.
- Existence state: observed local, observed remote, generated, expected, missing, declared-only.
- Visibility: public/private.
- Role.
- Description.
- Required flag.
- Hash and size for local files when policy permits.
- Copy/reference policy.
- Formal parameter mapping when known.

Parameter declarations MUST record concrete values as `PropertyValue` entities and link them to `FormalParameter` with `exampleOfWork` where appropriate.

### 9.9 `rcr software`

Software capture SHOULD attempt:

- `command --version` or tool-specific version command.
- Executable path.
- Package manager metadata if available.
- Container image metadata if applicable.
- Lockfiles: `requirements.txt`, `pyproject.toml`, `poetry.lock`, `uv.lock`, `environment.yml`, `package-lock.json`, `pnpm-lock.yaml`, `renv.lock`, `Snakefile`, `nextflow.config`, `Dockerfile`, `Containerfile`, CWL/WDL workflow files.

### 9.10 `rcr run --`

`rcr run -- <command>` MUST:

1. Generate a command event ID.
2. Assign or create a corresponding RO-Crate action ID in `id-map.json`.
3. Record start timestamp in UTC with `Z` suffix.
4. Record cwd and project root.
5. Record argv array when directly executable.
6. Record shell only when shell execution is used.
7. Record rendered command string as a display value.
8. Store a structured invocation sidecar JSON file under `.ro-crate-run/commands/`.
9. Capture stdout and stderr to files under `.ro-crate-run/logs/`.
10. Apply streaming redaction to logs when enabled.
11. Record selected allowlisted environment variables and environment summary.
12. Record Git state before and after.
13. Snapshot declared output paths and configured output roots before and after.
14. Append and flush `execution.command.started` before launching the subprocess.
15. Execute the command.
16. Record exit code, end timestamp, duration, signal if any, and failure class if applicable.
17. Hash declared inputs and outputs according to hash policy.
18. Append `execution.command.completed` or `execution.command.failed`.
19. Return the original command exit code.

Direct exec is preferred over shell execution. Shell execution MUST be explicit and recorded.

If startup recovery finds an `execution.command.started` event without a terminal completed/failed/blocked event, it MUST mark the command as abandoned or indeterminate and report it in validation rather than silently dropping the attempted execution.

---

## 10. Hook specification

### 10.1 General hook requirements

Project-local installs MUST register hooks in `.claude/settings.json`. Plugin installs MUST register hooks in `hooks/hooks.json` and ship the referenced scripts in the plugin `hooks/` directory.

Every hook script MUST:

1. Read Claude Code hook JSON from stdin. Treat the `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, and `CLAUDE_PLUGIN_DATA` environment variables that Claude Code exports to hook processes as supplemental context only. Do **not** rely on `${CLAUDE_SKILL_DIR}` — it is a skill-content substitution and is not exported to hooks; resolve the script/CLI location from `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PROJECT_DIR` or relative to the script's own path.
2. Validate minimal schema and event name.
3. Load `.ro-crate-run/state.json` if present.
4. Exit successfully without side effects when no run exists unless auto-start is configured.
5. Redact sensitive fields before persistence.
6. Append an event using the shared event writer.
7. Avoid recursive hook loops.
8. Respect mode-specific blocking behavior.
9. Emit actionable stderr on blocking failures.

### 10.2 Required hooks for v1

| Claude Code hook | Purpose | Events |
|---|---|---|
| `SessionStart` | Observe session start/resume context. | `session.started`, `run.resumed` |
| `UserPromptSubmit` | Capture redacted prompt or prompt hash/private record. | `human.prompt` |
| `PreToolUse` | Observe requested tool and optionally block risky raw commands. | `tool.requested`, `tool.blocked` |
| `PostToolUse` | Capture completed tool activity, file changes, command summaries. | `tool.completed`, `execution.command.*`, `file.*` |
| `PostToolUseFailure` | Capture failed tool activity. | `tool.failed` |
| `PostToolBatch` | Record batch boundary and optionally checkpoint. | `tool.batch.completed` |
| `Stop` | Checkpoint and validate before response completion. | `session.stop.requested`, `crate.checkpoint.*`, `crate.validation.*` |
| `SessionEnd` | Record session end and attempt non-blocking checkpoint. | `session.ended` |

### 10.3 Recommended hooks for v1.1

| Claude Code hook | Purpose | Events |
|---|---|---|
| `PermissionRequest` | Record permission request before tool use. | `permission.requested` |
| `PermissionDenied` | Record denied permission and avoid interpreting absence as success. | `permission.denied` |
| `StopFailure` | Capture blocked or failed stop/finalization path. | `session.stop.failed` |
| `CwdChanged` | Track working-directory changes. | `environment.cwd.changed` |
| `FileChanged` | Record explicit watched file change events. | `file.changed` |
| `WorktreeCreate` | Track Claude Code worktree creation. | `git.worktree.created` |
| `WorktreeRemove` | Track worktree removal. | `git.worktree.removed` |
| `PreCompact` | Record compaction boundary. | `conversation.compaction.started` |
| `PostCompact` | Record compaction summary metadata. | `conversation.compaction.completed` |
| `TaskCreated` | Track task/delegation creation. | `agent.task.created` |
| `TaskCompleted` | Track task/delegation completion. | `agent.task.completed` |
| `SubagentStart` | Track subagent execution. | `agent.subagent.started` |
| `SubagentStop` | Track subagent completion. | `agent.subagent.completed` |

### 10.4 Stop hook behavior

In advisory mode, the Stop hook MUST NOT block.

In monitored mode, the Stop hook SHOULD:

1. Check whether provenance-relevant events newer than `last_checkpoint.materialized_through_sequence` exist.
2. Run checkpoint if stale.
3. Run validation.
4. Block only on critical failures: materialization failure, invalid JSON-LD, privacy leakage, missing required outputs, or corrupt event journal.

In enforced mode, the Stop hook MUST block when:

1. The crate is stale and checkpoint fails.
2. Required validation fails.
3. Required outputs are missing.
4. A critical phase or step is open.
5. A substantive raw Bash command bypassed capture.
6. Public crate export would include unredacted sensitive data.

The hook MUST include remediation instructions in stderr.

---

## 11. Event journal specification

### 11.1 Format

`events.ndjson` is newline-delimited JSON. Each line is exactly one JSON object. The journal is append-only except for explicit repair/redaction workflows that produce a replacement journal and preserve tombstone/redaction events.

### 11.2 Base event schema

Every event MUST contain:

```json
{
  "event_id": "evt_...",
  "event_type": "execution.command.completed",
  "schema_version": "1.0.0",
  "run_id": "run_...",
  "session_id": "optional-claude-session-id",
  "sequence": 42,
  "timestamp": "2026-06-17T21:24:01.123456Z",
  "actor": {
    "type": "Person|SoftwareApplication|AIModel|System",
    "id": "actor:...",
    "name": "..."
  },
  "source": {
    "kind": "claude_hook|skill_command|human_cli|materializer|validator|ci",
    "name": "rocrate_post_tool_use.py",
    "version": "..."
  },
  "visibility": "private|public|derived-public",
  "phase_id": null,
  "step_id": null,
  "observed": true,
  "declared": false,
  "inferred": false,
  "redacted": false,
  "previous_event_hash": "sha256:...",
  "event_hash": "sha256:...",
  "payload": {}
}
```

### 11.3 Event hash chain

The event writer MUST calculate a canonical JSON representation excluding `event_hash`, then calculate:

```text
event_hash = sha256(canonical_event_json_with_previous_event_hash)
```

This provides tamper evidence, not tamper proofing. Stronger guarantees require signing, append-only remote storage, or trusted CI finalization.

### 11.4 Required event families

#### Run lifecycle

```text
run.started
run.resumed
run.config.updated
run.finalized
run.aborted
```

#### Session lifecycle

```text
session.started
session.ended
session.stop.requested
session.stop.failed
```

#### Human interaction

```text
human.prompt
human.note
human.decision
human.declared_input
human.declared_output
human.accepted_result
human.rejected_result
```

#### Workflow structure

```text
workflow.identified
workflow.phase.started
workflow.phase.completed
workflow.step.identified
workflow.step.started
workflow.step.completed
workflow.step.failed
workflow.parameter.declared
workflow.input.declared
workflow.output.declared
workflow.profile.selected
```

#### Tool and permission activity

```text
tool.requested
tool.completed
tool.failed
tool.blocked
tool.batch.completed
permission.requested
permission.denied
```

#### Command execution

```text
execution.command.started
execution.command.completed
execution.command.failed
execution.command.blocked
```

#### File and dataset events

```text
file.observed
file.created
file.modified
file.deleted
file.changed
file.hashed
dataset.observed
dataset.hashed
```

#### Software and environment

```text
software.observed
environment.observed
environment.cwd.changed
container.observed
git.state.observed
git.worktree.created
git.worktree.removed
dependency.lockfile.observed
```

#### Agent/task activity

```text
agent.task.created
agent.task.completed
agent.subagent.started
agent.subagent.completed
conversation.compaction.started
conversation.compaction.completed
```

#### Checkpoint and validation

```text
crate.checkpoint.started
crate.checkpoint.completed
crate.checkpoint.failed
crate.validation.completed
crate.validation.failed
crate.finalized
```

#### Redaction and repair

```text
redaction.applied
redaction.failed
journal.repair.started
journal.repair.completed
journal.repair.failed
```

### 11.5 Atomic write algorithm

The shared event writer MUST:

1. Acquire `.ro-crate-run/lock` using an OS-level file lock.
2. Load `state.json`.
3. Increment sequence.
4. Canonicalize and hash the event.
5. Append one JSON line to `events.ndjson`.
6. Flush and fsync where feasible.
7. Write `state.json.tmp`.
8. Atomically rename `state.json.tmp` to `state.json`.
9. Release lock.

Canonicalization MUST be specified exactly. The implementation SHOULD use RFC 8785 JSON Canonicalization Scheme where available; otherwise it MUST define and test an equivalent deterministic encoding, including UTF-8, sorted object keys, no insignificant whitespace, and stable number/string handling.

On startup, recovery MUST treat `events.ndjson` as authoritative over `state.json`: reject or repair partial trailing lines, recompute the hash chain, rebuild `sequence` and `last_event_hash`, and rewrite `state.json` if it lags a fully fsynced journal append. Recovery MUST emit a `journal.repair.*` event when it changes persistent state.

---

## 12. State specification

### 12.1 `state.json`

```json
{
  "schema_version": "1.0.0",
  "run_id": "run_20260617_212401_abcdef",
  "title": "Evaluate model variants on benchmark dataset",
  "description": null,
  "created_at": "2026-06-17T21:24:01Z",
  "updated_at": "2026-06-17T22:10:33Z",
  "sequence": 128,
  "last_event_hash": "sha256:...",
  "mode": "monitored",
  "selected_profile": "process",
  "profile_confidence": "high",
  "profile_uri": "https://w3id.org/ro/wfrun/process/0.5",
  "current_phase_id": "phase_preprocessing",
  "current_step_id": null,
  "crate_dir": ".ro-crate-run/ro-crate",
  "event_journal": ".ro-crate-run/events.ndjson",
  "id_map": ".ro-crate-run/id-map.json",
  "last_checkpoint": {
    "event_id": "evt_...",
    "timestamp": "2026-06-17T22:10:33Z",
    "event_sequence": 128,
    "materialized_through_sequence": 126,
    "validation_status": "passed"
  },
  "dirty": false,
  "declared_inputs": [],
  "declared_outputs": [],
  "known_outputs": [],
  "known_software": [],
  "privacy": {
    "include_prompts": false,
    "include_event_journal": false,
    "include_full_logs": false,
    "include_source_code_public": false,
    "include_git_diff_public": false
  },
  "warnings": [],
  "errors": []
}
```

### 12.2 Dirty state

`dirty` is true when:

- New provenance-relevant events exist after `last_checkpoint.materialized_through_sequence`.
- Declared inputs or outputs changed.
- Known output hashes changed.
- Validation failed after last checkpoint.
- Materializer version changed.
- Profile selection changed.
- Privacy/redaction policy changed.

Checkpoint and validation events that are produced by a checkpoint do not by themselves make the crate dirty. `dirty` is false only after successful checkpoint and validation whose `materialized_through_sequence` covers all provenance-relevant events.

---

## 13. Privacy and security specification

### 13.1 Capture risk

The system may encounter sensitive content in:

- User prompts.
- Claude responses.
- Commands.
- File paths.
- Environment variables.
- Logs.
- Error messages.
- Source code.
- Data filenames.
- Data contents.
- Secrets in `.env`, cloud credentials, SSH config, keychains, or tokens.

### 13.2 Default public/private policy

| Data class | Private journal default | Public crate default |
|---|---:|---:|
| Run title | Yes | Yes |
| User prompts | Redacted/hash | No |
| Human notes | Yes | Only if public |
| Human decisions | Yes | Only if public or required summary |
| Commands | Redacted | Summary + sidecar if safe |
| stdout/stderr logs | File capture with redaction | Include/reference only if safe and policy permits |
| Environment variables | Allowlisted only | Summary only |
| Git commit/branch/status | Yes | Yes unless private repo policy disables |
| Source code files | Yes metadata | Include/reference per file policy |
| Input datasets | Metadata/hash | Reference by default |
| Output artifacts | Metadata/hash | Include by default if size/privacy permit |
| Event journal | Yes | No unless explicitly enabled and redacted |

### 13.3 Redaction rules

The implementation MUST:

1. Redact before event append whenever feasible.
2. Use an allowlist for environment variables rather than capturing all environment variables.
3. Maintain denylist names for sensitive variables such as tokens, keys, secrets, passwords, cookies, credentials, and private keys.
4. Apply regex redaction for common secret formats.
5. Avoid reading `.env`, keychains, cloud credential files, SSH keys, or browser credential stores.
6. Preserve structure after redaction where possible.
7. Record `redaction.applied` events without storing redacted values.
8. Provide dry-run redaction validation before public export.

### 13.4 Public export gate

`rcr finalize --public` MUST fail if:

- Public crate includes raw prompt text without explicit `include_prompts=true`.
- Public crate includes event journal without explicit `include_event_journal=true`.
- Secret patterns are found in metadata, logs, command sidecars, or included files.
- Unredacted environment variables outside allowlist are present.
- Source code or Git diffs are included without explicit public-source/public-diff configuration and a passing secret scan.

---

## 14. Materializer specification

### 14.1 Materializer entry point

```text
rocrate_checkpoint.py
```

### 14.2 Responsibilities

The materializer MUST:

1. Acquire the run lock.
2. Load config, state, ID map, and event journal.
3. Determine `materialized_through_sequence`, the latest provenance-relevant event sequence that should be reflected in the crate.
4. Append `crate.checkpoint.started` with that high-water mark.
5. Validate journal syntax and hash chain.
6. Build an in-memory run model from events through `materialized_through_sequence`, excluding checkpoint/validation bookkeeping events generated for the same checkpoint.
7. Select or confirm profile.
8. Rebuild crate metadata from the event model.
9. Use ro-crate-py as the code path for crate construction and metadata writing.
10. Add contextual entities and custom terms with correct contexts or full URIs.
11. Copy, stage, or reference files according to policy.
12. Write `ro-crate-metadata.json`.
13. Run validation.
14. Write `run-summary.json` and `validation-report.json`.
15. Append checkpoint completion/failure event with `materialized_through_sequence`.
16. Update state and dirty flag.

### 14.3 Rebuild strategy

The v1 materializer MUST rebuild metadata from events rather than mutate the existing graph incrementally. It MAY reuse existing copied files if hash and policy match.

Rationale:

- Deterministic behavior.
- Easier testing.
- Less entity duplication.
- Easier upgrades after mapping fixes.

### 14.4 File policy

Default file policy:

```json
{
  "include_declared_inputs": false,
  "include_declared_outputs": true,
  "include_logs": "safe-and-size-limited",
  "include_source_code": "private-only",
  "include_git_diff": "private-only",
  "include_event_journal": false,
  "max_file_size_mb": 100,
  "copy_mode": "mixed"
}
```

Rules:

- Large inputs are referenced, not copied, unless explicitly requested.
- Outputs are included when size and privacy policy permit.
- Logs are linked to actions and may be copied or referenced.
- Workflow definitions and small source scripts are included by default in private/internal crates. Public export MUST include them only when explicitly allowed and after privacy scanning.
- Files outside the project root are referenced by URI/path abstraction only, unless explicitly copied.
- Symlinks MUST be resolved safely and must not exfiltrate outside allowed roots without explicit permission.

### 14.5 Hashing

Required algorithm: SHA-256.

Optional algorithms: BLAKE3 for internal performance, but SHA-256 remains the portable crate metadata hash.

For each hashed file record:

- `sha256` if the active context defines the term.
- Otherwise use `identifier` as a `PropertyValue` with `propertyID: sha256`.
- `contentSize`.
- `encodingFormat`.
- `dateModified`.

Large files MAY be marked not hashed with reason.

---

## 15. RO-Crate mapping specification

### 15.1 JSON-LD context

The metadata JSON-LD context MUST include:

- RO-Crate 1.2 context.
- Workflow-run context when using workflow-run-specific terms.
- Any additional profile contexts required by custom mapped terms.

Example:

```json
"@context": [
  "https://w3id.org/ro/crate/1.2/context",
  "https://w3id.org/ro/terms/workflow-run/context"
]
```

If a term is not mapped by these contexts, use a full URI or define a local context mapping intentionally.

### 15.2 Metadata descriptor

The descriptor entity MUST be:

```json
{
  "@id": "ro-crate-metadata.json",
  "@type": "CreativeWork",
  "about": {"@id": "./"},
  "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"}
}
```

Do not put run profile conformance here in RO-Crate 1.2 output. Profile conformance belongs on the Root Data Entity.

### 15.3 Root Data Entity

The root entity MUST represent the whole run:

```json
{
  "@id": "./",
  "@type": "Dataset",
  "name": "...",
  "description": "...",
  "datePublished": "2026-06-17T22:10:33Z",
  "dateCreated": "2026-06-17T21:24:01Z",
  "dateModified": "2026-06-17T22:10:33Z",
  "license": {"@id": "..."},
  "conformsTo": [
    {"@id": "https://w3id.org/ro/wfrun/process/0.5"}
  ],
  "hasPart": [],
  "mentions": []
}
```

The root entity MUST include an `@id` and the RO-Crate 1.2 root-required properties: `@type`, `name`, `description`, `datePublished`, and `license`. `dateCreated` and `dateModified` are additional run facts, not substitutes for `datePublished`. The base RO-Crate 1.2 conformance remains on the metadata descriptor; root `conformsTo` declares run profile conformance. Omit absent properties rather than serializing JSON `null`. For Workflow Run and Provenance Run, `mainEntity` MUST identify the main `ComputationalWorkflow` entity.

### 15.4 Profile entities

The crate SHOULD include contextual entities for each declared profile:

```json
{
  "@id": "https://w3id.org/ro/wfrun/process/0.5",
  "@type": "Profile",
  "name": "Process Run Crate",
  "version": "0.5"
}
```

### 15.5 Actors

Map actors as follows:

| Event actor | RO-Crate type | Notes |
|---|---|---|
| Human user | `Person` | Use a privacy-preserving stable ID unless user provides identity. |
| Claude Code | `SoftwareApplication` | Include version when available. |
| Claude model | `SoftwareApplication` or `ComputerProgram` | Include model name if safe and available. |
| Skill/CLI | `SoftwareApplication` | Include skill version and source. |
| ro-crate-py | `SoftwareApplication` | Include Python package version. |
| Python runtime | `SoftwareApplication` or `ComputerLanguage` | Include version. |
| Shell | `SoftwareApplication` | Include path/version if safe. |
| Workflow engine | `SoftwareApplication` | Snakemake, Nextflow, CWL runner, WDL engine, Galaxy, etc. |

### 15.6 Files and datasets

Local files are `File`. Directories and collections are `Dataset`.

Recommended file metadata:

```json
{
  "@id": "results/report.md",
  "@type": "File",
  "name": "report.md",
  "description": "Final benchmark report",
  "encodingFormat": "text/markdown",
  "contentSize": "12345",
  "dateModified": "2026-06-17T22:00:00Z",
  "identifier": {
    "@type": "PropertyValue",
    "propertyID": "sha256",
    "value": "..."
  }
}
```

Use `exampleOfWork` only when mapping a concrete file/value to a declared `FormalParameter`.

### 15.7 Software and workflow definitions

Installed tools are `SoftwareApplication`.

Source files are `SoftwareSourceCode` and `File`.

Workflow definitions MUST be represented as:

```json
{
  "@id": "workflow/Snakefile",
  "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
  "name": "Snakefile"
}
```

Add `HowTo` only when representing steps through `HowToStep` and provenance mapping requires it.

A script should be treated as a `ComputationalWorkflow` only when evidence indicates it orchestrates multiple steps, tools, services, or a clear dataflow. A Python script is not a workflow solely because it exists.

### 15.8 Command actions

Command events map to actions based on observed behavior:

| Observed behavior | Preferred type |
|---|---|
| Produces one or more new outputs | `CreateAction` |
| Modifies existing files in place | `UpdateAction` |
| Runs inspection/check without creating outputs | `Action` or `ActivateAction` |
| Deletes outputs | `DeleteAction` |
| Failed command relevant to run | Same intended action type plus failed status |

Completed `CreateAction` example:

```json
{
  "@id": "urn:uuid:...",
  "@type": "CreateAction",
  "name": "Run evaluation script",
  "description": "Executed evaluation command; full invocation recorded in command sidecar.",
  "startTime": "2026-06-17T21:30:00Z",
  "endTime": "2026-06-17T21:31:10Z",
  "actionStatus": {"@id": "http://schema.org/CompletedActionStatus"},
  "agent": {"@id": "#actor/claude-code"},
  "instrument": {"@id": "scripts/evaluate.py"},
  "object": [{"@id": "data/input.csv"}],
  "result": [{"@id": "results/report.md"}]
}
```

Logs and the command sidecar are represented as separate `File` entities that point back to the action with schema.org `about`, following the Workflow Run Crate convention for engine-generated traces and reports (see §15.9 and §2.3). `about` is placed on the `File` (not `workPerformed` or `subjectOf` on the action): schema.org `workPerformed` has domain `Event` (a creative work performed at an event) and is **not** a property of `Action`/`CreateAction`, so it MUST NOT be used to attach logs or sidecars.

```json
{
  "@id": ".ro-crate-run/commands/cmd_001.json",
  "@type": "File",
  "name": "cmd_001 invocation record",
  "encodingFormat": "application/json",
  "about": {"@id": "urn:uuid:..."}
}
```

```json
{
  "@id": ".ro-crate-run/logs/cmd_001.stdout.txt",
  "@type": "File",
  "name": "cmd_001 stdout",
  "encodingFormat": "text/plain",
  "about": {"@id": "urn:uuid:..."}
}
```

Failed action example, with the stderr log linked back to the failed action via `about`:

```json
{
  "@id": "urn:uuid:...",
  "@type": "CreateAction",
  "actionStatus": {"@id": "http://schema.org/FailedActionStatus"},
  "error": "Command exited with code 1; see stderr log."
}
```

```json
{
  "@id": ".ro-crate-run/logs/cmd_002.stderr.txt",
  "@type": "File",
  "name": "cmd_002 stderr",
  "encodingFormat": "text/plain",
  "about": {"@id": "urn:uuid:...failed-action..."}
}
```

### 15.9 Workflow Run mapping

For a Workflow Run Crate (whether the workflow is the agent's synthesized actions or an
external definition):

1. The root `conformsTo` includes Workflow Run Crate profile URI.
2. The root `mainEntity` points to the main `ComputationalWorkflow`.
3. The main workflow entity is a `ComputationalWorkflow` (and `SoftwareSourceCode`). When
   it is an external definition file it also has type `File` and appears in `hasPart`;
   when it is synthesized from the agent's actions (§16.5) it is abstract — a fragment
   `@id`, not a `File`, referenced via `mainEntity` only.
4. The workflow-level run action uses the workflow as `instrument`.
5. Workflow inputs and outputs are represented as `FormalParameter` entities.
6. Concrete files and values link to formal parameters via `exampleOfWork`.
7. Config files that are not formal workflow parameters MUST NOT use `exampleOfWork`.
8. Workflow engine logs/reports SHOULD be included or referenced and linked with `about` to relevant actions.

### 15.10 Provenance Run mapping

Promote to Provenance Run only when step-level details exist.

Requirements:

1. Root `conformsTo` includes Provenance Run Crate profile URI.
2. The workflow entity includes `HowTo` when step metadata is represented.
3. The workflow entity has `step` entries pointing to `HowToStep` entities.
4. Each `HowToStep` has `workExample` pointing to the corresponding tool or source code where known.
5. Each step execution has an action, usually `CreateAction` or `UpdateAction`.
6. A `ControlAction` links step definition to step execution:

```json
{
  "@id": "urn:uuid:...",
  "@type": "ControlAction",
  "instrument": {"@id": "#step/normalize"},
  "object": {"@id": "urn:uuid:...step-action..."}
}
```

7. Intermediate outputs are represented when observed or declared.
8. `ParameterConnection` MAY be used when source/target parameter connections are known.

### 15.11 Environment, containers, and dependencies

Represent environment variables as `PropertyValue` entities only when allowlisted and relevant.

Represent container images with workflow-run `ContainerImage` where available:

- registry.
- image name.
- tag.
- digest or SHA-256.

Represent dependencies via `softwareRequirements` on workflow/tool entities. Include lockfiles and build instructions when available.

### 15.12 Git and source state

The crate SHOULD include:

- Repository URL if public or allowed.
- Commit SHA.
- Branch name if allowed.
- Dirty-state summary.
- Patch/diff file when configured and safe.
- Worktree metadata if relevant.

A dirty working tree is not an error by default, but strict validation MAY require clean Git state or an included diff.

---

## 16. Profile selection

**The workflow is the agent's work.** In this skill the "workflow" is the set of
actions taken by the Claude Code agent(s) during the run — it is NOT tied to any
specific workflow-management system. An external workflow definition (CWL, Snakemake,
Nextflow, Galaxy, WDL, …), when present, is treated as *optional enrichment* of that
picture, never a precondition. When the Workflow or Provenance profile applies but no
external definition file was declared, the materializer MUST synthesize a
`ComputationalWorkflow` entity standing for the agent's run (see §16.5), so the crate
conforms without requiring a workflow-system file.

### 16.1 Default profile

Default profile: Process Run Crate.

Use Process Run when:

- The run is a single, flat command execution.
- One or more computational tools/scripts contribute to a result without explicit
  structure (no phases, no multiple distinct commands, no declared steps).

### 16.2 Upgrade to Workflow Run Crate

The agent's structured work constitutes the workflow. Upgrade when any holds:

1. The agent's work is structured: more than one command was executed, or one or more
   phases (`rcr phase`) were declared.
2. An external workflow definition is identified or explicitly declared (optional
   enrichment), with its engine/mechanism known or reasonably inferred.

A workflow-level execution action MUST be representable (it wraps the agent's commands).
External examples that enrich the picture: `workflow.cwl` run by `cwltool`; `main.nf`
run by Nextflow; `Snakefile` run by Snakemake; `workflow.ga` (Galaxy); `workflow.wdl`.

### 16.3 Upgrade to Provenance Run Crate

Upgrade when step-level execution evidence exists, with or without an external file.

Evidence may include:

- `rcr step` events and `rcr run --step` command mappings (the primary, agent-native path).
- Workflow engine step logs or native provenance export (when an external system is used).
- A known mapping from steps to execution actions, with observed intermediate outputs.

Each step is represented as a `HowToStep` linked to its execution action via a
`ControlAction`. Do not upgrade based only on human phase labels.

### 16.5 Synthesized agent workflow

When §16.2 or §16.3 applies and no external workflow definition file was declared, the
materializer synthesizes the main workflow from the agent's actions:

- An (abstract) `ComputationalWorkflow` entity with a fragment `@id`
  (`#workflow/agent-actions`), `programmingLanguage` `claude-code`, set as the root
  `mainEntity`. Being abstract (not a `File`), it is referenced via `mainEntity` and is
  not part of `hasPart`.
- For Provenance, the agent's declared steps (`rcr step`) become its `HowToStep`s with
  `ControlAction` links to the per-command actions.

An external definition, when declared (role `workflow-definition`), is used as-is and is
never overwritten by synthesis.

### 16.4 Profile selection event

The materializer MUST record profile selection:

```json
{
  "event_type": "workflow.profile.selected",
  "payload": {
    "selected_profile": "process|workflow|provenance",
    "profile_uri": "https://w3id.org/ro/wfrun/process/0.5",
    "reason": "...",
    "confidence": "low|medium|high",
    "evidence": []
  }
}
```

If profile selection changes, the run becomes dirty and must checkpoint again.

---

## 17. Validation specification

### 17.1 Validation levels

#### Level 0: Event journal integrity

Check:

- Valid NDJSON.
- Required event fields.
- Monotonic sequence.
- Valid timestamps.
- No duplicate event IDs.
- Valid hash chain.
- Valid redaction markers.
- `execution.command.started` events have a terminal completed, failed, blocked, or recovered-abandoned status unless the run is still active.

#### Level 1: State consistency

Check:

- `state.json` exists.
- `run_id` matches journal.
- `last_event_hash` matches journal.
- Last checkpoint sequence is valid.
- Dirty flag is accurate.
- Open phases/steps are represented.
- ID map is internally consistent.

#### Level 2: RO-Crate structure

Check:

- `ro-crate-metadata.json` exists.
- JSON is valid.
- JSON-LD expands.
- Metadata descriptor exists.
- Descriptor `about` points to root.
- Descriptor conforms to RO-Crate 1.2 base spec.
- Root Data Entity exists and is `Dataset`.
- Root has `name`.
- Root has `description`.
- Root has `datePublished`.
- Root has `license`.
- Root has selected profile conformance.
- Root does not use JSON `null` values for absent relationships.
- Files referenced by included relative IDs exist unless marked external/reference.

#### Level 3: Profile rules

Process Run:

- At least one relevant action or explicit no-action rationale.
- Completed creating actions have `instrument` where known.
- Completed actions have `startTime`, `endTime`, and `actionStatus` when observed.
- Declared inputs/outputs are represented.
- Failed relevant commands use failed action status and error/log references.

Workflow Run:

- Process Run rules pass.
- `ComputationalWorkflow` entity exists.
- Root `mainEntity` points to workflow.
- Workflow execution action uses workflow as `instrument`.
- Formal parameters exist where known.
- Concrete parameter examples use `exampleOfWork` correctly.

Provenance Run:

- Workflow Run rules pass.
- Step-level actions exist.
- `HowToStep` entities exist when step definitions are known.
- `ControlAction` links step definitions to executions.
- Intermediate outputs are represented where observed.
- Parameter connections are represented when known.

#### Level 4: Reproducibility quality warnings

Warn on:

- Missing Git commit.
- Dirty working tree without diff.
- Missing software versions.
- Missing hashes for local inputs.
- Missing declared outputs.
- Missing environment summary.
- Missing container digest for containerized run.
- Missing lockfiles for dependency-managed projects.
- Missing human rationale for manual parameter changes.

#### Level 5: Privacy and release gate

Fail public export on:

- Detected secrets.
- Raw prompts without explicit inclusion.
- Full event journal without explicit inclusion.
- Unredacted logs containing secret patterns.
- Environment variables outside allowlist.

### 17.2 Validation output

Machine-readable:

```json
{
  "status": "passed|warning|failed",
  "profile": "process",
  "profile_uri": "https://w3id.org/ro/wfrun/process/0.5",
  "levels": {
    "journal": "passed",
    "state": "passed",
    "ro_crate": "passed",
    "profile": "warning",
    "reproducibility": "warning",
    "privacy": "passed"
  },
  "errors": [],
  "warnings": [],
  "recommendations": []
}
```

Human-readable:

```text
RO-Crate validation: passed with warnings
Profile: Process Run Crate 0.5

Warnings:
- 2 local inputs are referenced but not hashed.
- Git working tree had uncommitted changes at run start.
```

---

## 18. Enforcement and CI

### 18.1 PreToolUse blocking policy

In enforced mode, block:

- Raw Bash commands that perform substantive work without `rcr run --`.
- Commands writing into declared output roots without capture.
- Destructive commands that delete evidence unless explicitly allowed.
- Commands matching secret exfiltration or unsafe patterns.

Allow by default:

- `pwd`.
- `ls`.
- `git status`.
- `git rev-parse`.
- Non-sensitive `cat`/`head`/`tail` inspection.
- Provenance scripts themselves.

### 18.2 Stop hook enforcement

In enforced mode, Stop hook MUST block if:

- Crate is stale and checkpoint fails.
- Validation errors exist.
- Required outputs are missing.
- Critical phase/step is open.
- Raw substantive Bash bypassed capture.
- Privacy export gate fails.

### 18.3 CI command

Recommended CI invocation:

```bash
python3 .claude/skills/ro-crate-run/scripts/rocrate_validate.py --strict
```

CI SHOULD fail if:

- Provenance-relevant events exist after `last_checkpoint.materialized_through_sequence`.
- Validation status is failed.
- Required outputs are missing.
- Public export contains secrets.
- Strict reproducibility policy fails.

---

## 19. Configuration

Default `.ro-crate-run/config.json`:

```json
{
  "schema_version": "1.0.0",
  "mode": "monitored",
  "default_profile": "process",
  "profile_version": "0.5",
  "ro_crate_version": "1.2",
  "project_name": null,
  "crate_name": null,
  "copy_mode": "mixed",
  "output_roots": ["results", "outputs", "reports"],
  "input_roots": ["data", "inputs"],
  "source_roots": ["src", "scripts", "workflow", "workflows"],
  "ignore_patterns": [
    ".git/**",
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    ".mypy_cache/**",
    ".pytest_cache/**",
    ".ro-crate-run/staging/**"
  ],
  "hash_policy": {
    "algorithm": "sha256",
    "max_file_size_mb": 100,
    "hash_large_files": false
  },
  "file_policy": {
    "include_declared_inputs": false,
    "include_declared_outputs": true,
    "include_logs": "safe-and-size-limited",
    "include_source_code": "private-only",
    "include_git_diff": "private-only",
    "include_event_journal": false,
    "max_log_size_mb": 10
  },
  "privacy": {
    "include_prompts": false,
    "include_event_journal": false,
    "include_full_logs": false,
    "include_source_code_public": false,
    "include_git_diff_public": false,
    "public_by_default": false
  },
  "redaction": {
    "enabled": true,
    "patterns_file": ".ro-crate-run/secrets-redaction.json",
    "environment_allowlist": ["PATH", "LANG", "LC_ALL", "SHELL", "PYTHONPATH", "CONDA_DEFAULT_ENV", "VIRTUAL_ENV"]
  },
  "validation": {
    "strict": false,
    "require_git_commit": false,
    "require_clean_git": false,
    "require_declared_outputs": true,
    "require_software_versions": true,
    "require_date_published": true,
    "require_privacy_gate": true
  }
}
```

---

## 20. Dependency and packaging requirements

### 20.1 Runtime dependencies

- Python 3.9 or newer.
- `rocrate` / ro-crate-py, pinned after integration testing.
- JSON Schema or Pydantic for event validation.
- `filelock` or equivalent for cross-platform locks.
- Optional: `rdflib` for JSON-LD expansion checks.
- Optional: `pyshacl` for SHACL profile checks.
- Optional: `python-magic` or standard MIME detection fallback.

### 20.2 Dependency pinning

Initial recommendation:

```text
rocrate>=0.15,<0.16
```

This range should be updated only after testing metadata output and write/write_zip behavior.

### 20.3 Script packaging

All scripts MUST:

- Work from project root.
- Resolve their own location from `CLAUDE_PLUGIN_ROOT` (plugin distribution) or `CLAUDE_PROJECT_DIR` (project distribution) when present. `${CLAUDE_SKILL_DIR}` is a `SKILL.md` content substitution and is **not** available as an environment variable to scripts or hook subprocesses, so scripts MUST NOT depend on it.
- Fall back to locating the skill directory relative to the script's own path when no environment variable is set (for example, direct human terminal use).
- Avoid network calls unless explicitly requested.
- Produce deterministic JSON output for `--json` modes.

---

## 21. Testing strategy

### 21.1 Unit tests

Test:

- Event schema validation.
- Redaction.
- Hash chain generation.
- Locking and atomic state writes.
- Profile selection.
- Stable ID mapping.
- File copy/reference policy.
- Hashing large-file skip behavior.
- ro-crate-py entity creation.
- JSON-LD context inclusion.
- Validation rules.

### 21.2 Integration tests

Scenarios:

1. Start -> run command -> output -> checkpoint.
2. Resume existing run.
3. Failed command with stderr log.
4. Raw Bash blocked in enforced mode.
5. Stop hook checkpoints stale crate.
6. Stop hook blocks invalid crate in enforced mode.
7. Formal workflow file detected and declared.
8. Provenance profile selected from step-level events.
9. Redaction of secrets in prompt, command, env, and log.
10. Large dataset referenced but not copied.
11. Public export excludes prompts and event journal.
12. Final ZIP generated.
13. Worktree event captured.
14. Subagent task event captured.

### 21.3 Golden crate tests

Maintain fixture crates:

- Minimal Process Run Crate.
- Multi-command Process Run Crate.
- Failed-command Process Run Crate.
- Workflow Run Crate with Snakemake or CWL definition.
- Provenance Run Crate with two steps and intermediate output.
- Privacy-safe public crate.

Golden tests compare:

- Required graph entities.
- Profile conformance declarations.
- Stable identifiers.
- Key relationships.
- Validation output.
- Absence of private prompts/secrets.

### 21.4 Manual acceptance tests

Acceptance criteria:

- A user can start a run with one command.
- Claude can use the skill without hand-writing JSON-LD.
- A long session can checkpoint repeatedly.
- The final crate validates.
- Human decisions are represented.
- Commands, logs, and outputs are traceable.
- Missing metadata is clearly reported.
- Public export does not leak prompts or secrets by default.

---

## 22. Implementation phases

### Phase 1: Minimal Process Run Crate

Deliver:

- `rcr start`, `resume`, `status`, `note`, `input`, `output`, `run`, `checkpoint`, `validate`, `finalize`.
- Private event journal with hash chain.
- Basic redaction.
- Process Run Crate mapping.
- Base hooks: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, SessionEnd.
- ro-crate-py materializer.

Exit criteria:

- Produces valid Process Run Crate for a multi-command ad hoc analysis.

### Phase 2: Enforcement and privacy gate

Deliver:

- Monitored/enforced mode behavior.
- PreToolUse blocking policy.
- Stop hook blocking.
- CI validation.
- Public export privacy gate.
- Log redaction and size policies.

Exit criteria:

- Enforced mode cannot complete with stale/invalid/private-leaking provenance.

### Phase 3: Workflow Run Crate

Deliver:

- Workflow definition detection and explicit declaration.
- Workflow engine detection.
- `ComputationalWorkflow` mapping.
- Formal input/output mapping.
- Engine trace/log linking.
- Adapters for at least two workflow systems.

Exit criteria:

- Generates Workflow Run Crate for at least two workflow systems.

### Phase 4: Provenance Run Crate

Deliver:

- `rcr step` and `rcr run --step` end-to-end.
- Step parser/adapters for selected engines.
- `HowToStep`, `ControlAction`, intermediate output mapping.
- Optional `ParameterConnection` support.

Exit criteria:

- Generates Provenance Run Crate for a small multi-step workflow with intermediate outputs.

### Phase 5: Hardening and ecosystem integration

Deliver:

- Signature support.
- Remote append-only journal option.
- HTML preview.
- Native import adapters from workflow exporters.
- Repository/export integrations.
- Advanced SHACL/JSON Schema profile validation.

Exit criteria:

- Suitable for team-wide versioned plugin distribution.

---

## 23. Final engineering principles

1. Hooks record observed facts.
2. Wrappers capture command execution.
3. Humans provide intent, rationale, and declarations.
4. Claude interprets, labels, summarizes, and asks for missing metadata.
5. The event journal is the source of truth.
6. ro-crate-py writes the crate.
7. Validation decides whether the crate is acceptable.
8. Privacy rules decide what can be public.
9. Profile promotion is evidence-based, not aspirational.
10. The crate should be useful even when it is not perfect; uncertainty must be explicit.

---

## 24. Reference sources

Accessed 2026-06-17 unless noted.

[R1] RO-Crate Metadata Specification 1.2. https://www.researchobject.org/ro-crate/specification/1.2/  
[R2] RO-Crate 1.2 Root Data Entity and metadata descriptor requirements. https://www.researchobject.org/ro-crate/specification/1.2/root-data-entity.html  
[R3] RO-Crate 1.2 Profiles. https://www.researchobject.org/ro-crate/specification/1.2/profiles  
[R4] RO-Crate 1.2 Workflows and Scripts. https://www.researchobject.org/ro-crate/specification/1.2/workflows.html  
[R5] Workflow Run RO-Crate profile collection. https://www.researchobject.org/workflow-run-crate/profiles/  
[R6] Process Run Crate 0.5. https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/  
[R7] Workflow Run Crate 0.5. https://www.researchobject.org/workflow-run-crate/profiles/workflow_run_crate/  
[R8] Provenance Run Crate 0.5. https://www.researchobject.org/workflow-run-crate/profiles/provenance_run_crate/  
[R9] Soiland-Reyes, S. et al. Packaging research artefacts with RO-Crate. arXiv:2108.06503. https://arxiv.org/abs/2108.06503  
[R10] Goble, C. et al. / Workflow Run RO-Crate authors. Recording provenance of workflow runs with RO-Crate. arXiv:2312.07852. https://arxiv.org/abs/2312.07852  
[R11] ro-crate-py GitHub repository. https://github.com/ResearchObject/ro-crate-py  
[R12] rocrate package on PyPI. https://pypi.org/project/rocrate/  
[R13] Claude Code Skills documentation. https://docs.anthropic.com/en/docs/claude-code/skills  
[R14] Claude Code Hooks reference. https://docs.anthropic.com/en/docs/claude-code/hooks  
[R15] Claude Code Settings. https://docs.anthropic.com/en/docs/claude-code/settings  
[R16] Claude Code Plugins. https://docs.anthropic.com/en/docs/claude-code/plugins  
[R17] Bioschemas ComputationalWorkflow profile. https://bioschemas.org/profiles/ComputationalWorkflow  
[R18] Bioschemas FormalParameter profile. https://bioschemas.org/profiles/FormalParameter  
[R19] W3C PROV-O: The PROV Ontology. https://www.w3.org/TR/prov-o/  
[R20] Schema.org Action and CreateAction. https://schema.org/Action and https://schema.org/CreateAction  
[R21] CodeMeta terms, including build instructions in computational contexts. https://codemeta.github.io/  
[R22] McPhillips, T. et al. YesWorkflow: A User-Oriented, Language-Independent Tool for Recovering Workflow Information from Scripts. https://doi.org/10.1007/s10618-015-0422-3
