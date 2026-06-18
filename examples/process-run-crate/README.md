# Process Run Crate Example

```bash
rcr start "Minimal process example" --no-checkpoint
printf 'sample\n' > input.txt
rcr input input.txt --role primary-dataset
rcr run --inputs input.txt --outputs result.txt -- python3 -c "open('result.txt','w').write('result\n')"
rcr finalize --public
```
