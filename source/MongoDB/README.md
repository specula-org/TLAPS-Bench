# MongoDB distributed transactions

Source: [mongodb-labs/vldb25-dist-txns](https://github.com/mongodb-labs/vldb25-dist-txns/tree/74526c1201109405172eb845413154f547a815ee),
the artifact for [Design and Modular Verification of Distributed Transactions in MongoDB](https://www.vldb.org/pvldb/vol18/p5045-schultz.pdf).
`MultiShardTxn.tla`, `Storage.tla`, `ClientCentric.tla`, and `Util.tla` are
copied unchanged; `upstream.json` records their commit and SHA-256 hashes.

`MultiShardTxnSnapshot.tla` adds this proof-from-scratch target:

```tla
(Spec /\ []SingleWritePerKey) => []SnapshotIsolation
```

`SingleWritePerKey` requires each transaction history in `ops`, the histories
passed to `SnapshotIsolation`, to write each key at most once. It formalizes
the [maintainer's stated assumption](https://github.com/mongodb-labs/vldb25-dist-txns/pull/3#issuecomment-5666002688),
also documented in `ClientCentric.tla`. It compares sequence positions so
identical write records count as separate writes. Transactions may write
multiple different keys and may read a key repeatedly.

The wrapper uses the upstream snapshot configuration:
`RC = "snapshot"`, `IgnorePrepareBlocking = "false"`, and
`IgnoreWriteConflicts = "false"`. It also requires `Timestamps \subseteq Nat`,
consistent with the model's natural-number timestamp convention and its
timestamp comparisons and arithmetic. Zero is allowed, with no upper bound
on timestamp values or cardinality bound on any parameter set. There is no
reference TLAPS proof and no proof-completion task.

Bounded TLC checks enforce the premise using `Init /\ SingleWritePerKey`
and `Next /\ SingleWritePerKey'`. A two-router, two-shard, two-key,
two-transaction model with read timestamps `{1,3}` and `MaxOpsPerTxn = 1`
explored 62,708 distinct states without a violation. A three-transaction
simulation with read timestamps `{1,2,3,4,5}` and `MaxOpsPerTxn = 4` completed
10,000 traces at depth limit 100 with seed `20260915`.

Controls confirm that the premise excludes the write/read/write history,
allows multiple keys and repeated reads, and preserves the prepare-blocking
and late-commit checks. These checks used TLC revision `5dbdb42`, at most two
workers and a 512 MiB heap. They provide bounded evidence for the task; the
complete theorem remains unproved.

Timestamp-domain controls reject Boolean and negative values during assumption
evaluation and accept zero, large natural numbers, and the empty set. A local
TLAPS check also derives `ts + 1 \in Nat` for every `ts \in Timestamps` from
the generated context's assumptions.

Regenerate the task and module suite with:

```sh
uv run python -m dataset.proof_from_scratch.generate --filter /MongoDB/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
```

The pinned repository has no repository-wide license file. `ClientCentric.tla`
identifies its BSD-2-Clause source; see the MongoDB entry in `NOTICE` and
`LICENSES/tla-ci-BSD-2-Clause.txt`.
