# Profile Selection Rules

## Profiles (SPEC §16)

Three run-profile levels exist, each a superset of the previous:

1. **Process Run Crate** — `https://w3id.org/ro/wfrun/process/0.5` — records commands without workflow structure.
2. **Workflow Run Crate** — `https://w3id.org/ro/wfrun/workflow/0.5` — adds a formal workflow definition + engine.
3. **Provenance Run Crate** — `https://w3id.org/ro/wfrun/provenance/0.5` — adds per-step actions and evidence.

## Automatic Promotion (SPEC §16.2)

Selection is performed by `materialize/profiles.select_profile`. With `requested_profile = "auto"`:

| Condition                                                          | Selected profile  | Confidence |
|--------------------------------------------------------------------|-------------------|------------|
| Formal workflow definition + engine + workflow-level IO + action   | workflow          | medium     |
| Above AND step-level actions + evidence                            | provenance        | high       |
| None of the above                                                  | process           | high (cmds)|
| No commands recorded yet                                           | process           | low        |

Workflow adapter detection (`adapters.detect_engine`) is called during profile selection to discover engine
and step IDs from the workflow definition file, feeding provenance promotion even when no explicit
`rcr step` events were recorded.

## Forced Profiles

If `requested_profile` is `"process"`, `"workflow"`, or `"provenance"`, that profile is used
unconditionally with `confidence: "high"`.

## Event Payload for Profile Selection

The `workflow.profile.selected` event carries:

```json
{
  "profile": "provenance",
  "profile_uri": "https://w3id.org/ro/wfrun/provenance/0.5",
  "confidence": "high",
  "evidence": [
    {"kind": "workflow", "path": "Snakefile"},
    {"kind": "steps", "count": 3}
  ]
}
```

## Adapter-Driven Step Discovery

When a workflow file is present, adapters are consulted:

- **Snakemake**: parses `rule` blocks from `Snakefile` / `*.smk`; returns steps list.
- **CWL**: parses `steps:` keys from `*.cwl` YAML.
- **Nextflow**: parses `process` declarations from `*.nf`.
- **Galaxy**: reads step names from `*.ga` JSON workflow files.

Discovered steps are merged into `model.steps` with status `"identified"` if not already present.

## Phase Labels vs Profile

Phase labels (from `rcr phase`) record logical phases of a project but do NOT by themselves
trigger profile promotion. Profile selection is driven by workflow/step evidence only.
