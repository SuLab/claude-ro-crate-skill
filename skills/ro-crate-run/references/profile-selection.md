# Profile Selection Rules

## Profiles (SPEC §16)

Three run-profile levels exist, each a superset of the previous:

1. **Process Run Crate** — `https://w3id.org/ro/wfrun/process/0.5` — records commands without workflow structure.
2. **Workflow Run Crate** — `https://w3id.org/ro/wfrun/workflow/0.5` — adds a formal workflow definition + engine.
3. **Provenance Run Crate** — `https://w3id.org/ro/wfrun/provenance/0.5` — adds per-step actions and evidence.

## The workflow is the agent's actions

In this skill the **workflow is the set of actions taken by the Claude Code agent(s)**,
not a specific workflow-management system. An external workflow definition (CWL,
Snakemake, Nextflow, Galaxy, WDL) is *optional enrichment*, never required. When the
workflow/provenance profile applies and no external definition file was declared, the
materializer synthesizes an abstract `ComputationalWorkflow` (`#workflow/agent-actions`)
standing for the agent's run, so the crate still conforms.

## Automatic Promotion (SPEC §16)

Selection is performed by `materialize/profiles.select_profile`. With `requested_profile = "auto"`:

| Condition                                                              | Selected profile  | Confidence |
|------------------------------------------------------------------------|-------------------|------------|
| Step execution evidence (`rcr step` execution or `rcr run --step`)     | provenance        | high       |
| External workflow definition declared                                  | workflow          | medium/high|
| Structured agent work: phases, or more than one command                | workflow          | medium     |
| A single, flat command                                                 | process           | high       |
| No commands recorded yet                                               | process           | low        |

Workflow adapter detection (`adapters.detect_engine`) is still called when an external
definition file is present, to discover engine and step IDs from it.

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

Phase labels (from `rcr phase`) are structured agent work, so they DO promote `auto` runs
to Workflow Run Crate (the phases are part of the agent's workflow). They do NOT by
themselves reach Provenance Run Crate — that still requires step-level execution evidence
(`rcr step` / `rcr run --step`).
