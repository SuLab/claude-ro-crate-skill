# Workflow Run Crate Example

```bash
rcr start "Workflow example" --profile auto --no-checkpoint
rcr input Snakefile --role workflow-definition --copy
rcr run --outputs results/out.txt -- python3 -c "import pathlib; pathlib.Path('results').mkdir(exist_ok=True); pathlib.Path('results/out.txt').write_text('ok')"
rcr checkpoint --profile auto
```
