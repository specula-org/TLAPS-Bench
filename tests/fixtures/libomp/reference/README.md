# libomp reference proof

The proof establishes all four benchmark goals for arbitrary domains satisfying
the runtime's assumptions. Its five-part inductive invariant tracks typing,
task-team parity, barrier phases, outstanding work, and the unfinished-thread
counter. Each runtime action preserves that invariant; the temporal proof then
derives the four goals.

`manifest.json` pins the runtime bytes and lists the complete proof dependency
chain. Every proof module must be checked with `tlapm --strict --nofp`; checking
only `LibompReference.tla` would trust imported lemmas without checking their
proofs. The runtime is copied from `source/libomp/libompRuntime.tla` when running
the regression test. It contains no admitted theorem.

Run the complete certificate check with:

```sh
uv run pytest -q tests/dataset/test_libomp.py -k reference
```

These files are validation artifacts. They are outside `source/` and both
generated benchmark trees, and are not in the task's context manifest.
