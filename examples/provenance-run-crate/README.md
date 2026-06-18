# Provenance Run Crate Example

```bash
rcr start "Provenance example" --profile auto --no-checkpoint
rcr input workflow.cwl --role workflow-definition --copy
rcr step start normalize
rcr run --step normalize --outputs normalized.tsv -- python3 -c "open('normalized.tsv','w').write('n')"
rcr step end normalize
rcr checkpoint --profile auto
```
