# MongoDB distributed transactions

Source: [mongodb-labs/vldb25-dist-txns](https://github.com/mongodb-labs/vldb25-dist-txns/tree/74526c1201109405172eb845413154f547a815ee),
the artifact for [Design and Modular Verification of Distributed Transactions in MongoDB](https://www.vldb.org/pvldb/vol18/p5045-schultz.pdf).
`MultiShardTxn.tla`, `Storage.tla`, `ClientCentric.tla`, and `Util.tla` are
copied unchanged; `upstream.json` records their commit and SHA-256 hashes.

`MultiShardTxnSnapshot.tla` adds the proof-from-scratch target
`Spec => []SnapshotIsolation`, under the upstream snapshot configuration:
`RC = "snapshot"`, `IgnorePrepareBlocking = "false"`, and
`IgnoreWriteConflicts = "false"`. It adds no bounds on router, shard, key,
transaction, or timestamp sets. There is no reference TLAPS proof and no
proof-completion task.

Bounded TLC checks of the pinned model found no violation: a two-router,
two-shard, two-key, two-transaction model with read timestamps `{1,3}` and
`MaxOpsPerTxn = 1` explored 62,708 distinct states; a three-transaction
simulation with read timestamps `{1,2,3,4,5}` and `MaxOpsPerTxn = 4`
completed 10,000 traces. These are model-checking results, not a general proof.

Regenerate the task and module suite with:

```sh
uv run python -m dataset.proof_from_scratch.generate --filter /MongoDB/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
```

The pinned repository has no repository-wide license file. `ClientCentric.tla`
identifies its BSD-2-Clause source; see the MongoDB entry in `NOTICE` and
`LICENSES/tla-ci-BSD-2-Clause.txt`.
