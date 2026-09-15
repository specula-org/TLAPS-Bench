# Cahill serializable snapshot isolation

Source: [pron/amazon-snapshot-spec](https://github.com/pron/amazon-snapshot-spec/tree/9c60cb18151889d7b4c0a4ffd7de0b6fc2db0fb2),
written by Chris Newcombe for HPTS 2011. The benchmark candidate was proposed
in [issue #145](https://github.com/specula-org/tlaps-bench/issues/145).

`CahillSerializability.tla` supplies one Proof From Scratch target:

```tla
Spec => []CahillSerializable(history)
```

`CahillSerializable` requires the committed transaction dependency graph to
remain acyclic. `Spec` retains the source's initialization, next-state action,
stuttering, and weak fairness. The original actions already restrict each
transaction to at most one read and one write per key. The wrapper adds no
parameter bounds or behavioral assumptions. No reference proof is supplied.

The original `serializableSnapshotIsolation.tla` is retained after a lossless
Windows-1252 to UTF-8 conversion, with its original line endings. Both hashes
are recorded in `upstream.json`.

The pinned TLAPM cannot parse recursive operator definitions or tuple binders.
`CahillSSIModel.tla` is a separate proof-compatible rendering:

- `BuildAbortOpSeq` becomes a recursive function over subsets of its input.
- `extendPath` becomes a recursive function over nonempty sequences of active
  transactions.
- `findCycleNodes` becomes a recursive function over graph nodes and visited
  node sets.
- Tuple binders become scalar binders with tuple projections on their
  pair-valued domains.

The replacements are listed in `tlaps-compatibility.json`; `prepare.py`
reproduces the rendering and verifies its hash. The adaptations follow the
[TLAPS feature limitations](https://proofs.tlapl.us/doc/web/content/Documentation/Unsupported_features.html).
Generated task contexts remove the source's two unproved theorem declarations.

Bounded validation uses TLC `5dbdb42`, at most two workers and a 512 MiB heap:

- Both representations complete a two-key, two-transaction exhaustive check:
  29,629 distinct states, depth 13, with no violations of the target, the
  independent Bernstein serializability predicate, or the checked SI and
  history invariants.
- Mutual refinement checks between the original and compatible specifications
  complete over the same model. The dependency graphs also agree in every
  checked state. The cycle helpers agree on all 512 directed graphs over three
  nodes.
- A two-key, three-transaction simulation completes 2,000 traces at depth 50
  with seed `20260915` for each representation.
- A write-skew control confirms that both serializability predicates reject
  a well-formed but nonserializable history. Replaying the attempted scenario
  through the original actions aborts one of the conflicting transactions;
  both representations complete the 12-state control.

For TLC, `NoLock` is instantiated with a fresh model value outside `Key` and
`TxnId`, matching its source definition. The proof task retains the original
`CHOOSE` definition. These checks provide bounded evidence for the task and
its compatibility adaptation, not complete proofs.

Regenerate with:

```sh
python3 source/CahillSSI/prepare.py --check
uv run python -m dataset.proof_from_scratch.generate source/CahillSSI/CahillSerializability.tla --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
```

No upstream license declaration is present. Attribution is recorded in `NOTICE`.
