# RO-Crate Mapping Policy

## Descriptor vs Root Entity (SPEC §15)

- The metadata descriptor (`ro-crate-metadata.json`) conforms to RO-Crate 1.2 — its `conformsTo` MUST be `https://w3id.org/ro/crate/1.2`.
- The Root Data Entity (`./`) carries the run-profile `conformsTo` URI (Process/Workflow/Provenance), plus `name`, `description`, `datePublished`, and `license`.
- Never duplicate `conformsTo` between descriptor and root; they serve different purposes.

## Actor Mapping (SPEC §15.5)

| source_kind           | @type               | @id                | name            |
|-----------------------|---------------------|--------------------|-----------------|
| human_cli             | Person              | actor:human        | Human operator  |
| claude_hook           | SoftwareApplication | actor:claude-code  | Claude Code     |
| skill_command         | SoftwareApplication | actor:rcr          | RO-Crate Run    |
| materializer          | SoftwareApplication | actor:rcr          | RO-Crate Run    |
| validator             | SoftwareApplication | actor:rcr          | RO-Crate Run    |
| ci                    | System              | actor:ci           | CI              |

## File and Dataset Rules (SPEC §15.6)

- Every captured file is a `File` entity with `@id` relative to the crate root.
- Files outside the crate root are referenced (not copied) with an absolute or `../` relative path.
- SHA-256 checksums are recorded as `identifier` `PropertyValue` with `propertyID: sha256`.
- Symlinks are resolved to their real path before hashing; if the target is outside the crate, treat as a reference.
- Logs are `File` entities with schema.org `about` pointing to their action entity.

## Software and Workflow Definition (SPEC §15.7)

- Any captured software tool is a `SoftwareApplication` entity.
- A script becomes `["File", "SoftwareSourceCode", "ComputationalWorkflow"]` ONLY when it orchestrates multiple steps — a single-command script is NOT a workflow definition.
- Workflow engine is a `SoftwareApplication` (`#actor/engine/<engine>`) with a `name` field.

## Command Action Type Selection (SPEC §15.8)

| Condition                                        | @type          | actionStatus          |
|--------------------------------------------------|----------------|-----------------------|
| New outputs, no pre-existing inputs modified     | CreateAction   | CompletedActionStatus |
| Inputs also appear as outputs (in-place modify)  | UpdateAction   | CompletedActionStatus |
| Declared deletions                               | DeleteAction   | CompletedActionStatus |
| No outputs declared                              | Action         | CompletedActionStatus |
| Any exit_code != 0                               | (same type)    | FailedActionStatus    |

## Formal Parameters (SPEC §15.9)

- `FormalParameter` entities are emitted for declared workflow inputs/outputs.
- Config files that are not workflow-level inputs/outputs are NOT formal parameters.
- Use `exampleOfWork` on `PropertyValue` to link a concrete value to its `FormalParameter`.

## HowToStep / ControlAction / ParameterConnection (SPEC §15.10)

- Each workflow step is a `HowToStep` entity with `name` and optional `position`.
- `ControlAction` links a `CreateAction` to its `HowToStep` via `instrument`.
- `ParameterConnection` with `sourceParameter`/`targetParameter` links output params to downstream step inputs — emit only when connections are explicitly declared.

## Environment, Container, Dependency (SPEC §15.11)

- Capture OS, Python version, CPU/memory as `PropertyValue` entities on the run action.
- Container images: `ContainerImage` entity with `registry`, `name`, `tag`, and `sha256` properties.
- Dependency lock files: `File` entities attached to the root action.

## Git / Source State (SPEC §15.12)

- Record `commit`, `branch`, `dirty` flag, and `remote_url` as `PropertyValue` entities on the root action.
- If working tree is dirty, note the diff path in the crate but do not include diff content unless `file_policy.include_git_diff` is true.
