# MongoDB distributed transactions

Source: [mongodb-labs/vldb25-dist-txns](https://github.com/mongodb-labs/vldb25-dist-txns/tree/7e299d4bc94ef9cdd24e91985944bb1e46623601),
the artifact for [Design and Modular Verification of Distributed Transactions in MongoDB](https://www.vldb.org/pvldb/vol18/p5045-schultz.pdf).
`MultiShardTxn.tla`, `Storage.tla`, `ClientCentric.tla`, and `Util.tla` are
copied unchanged; `upstream.json` records their commit and SHA-256 hashes.
This revision is the head of [upstream PR #3](https://github.com/mongodb-labs/vldb25-dist-txns/pull/3),
which makes `Index` select the first matching position. Upstream acceptance is
pending; the benchmark PR remains Draft until that dependency is resolved.

`MultiShardTxnSnapshot.tla` adds the proof-from-scratch target
`Spec => []SnapshotIsolation`, under the upstream snapshot configuration:
`RC = "snapshot"`, `IgnorePrepareBlocking = "false"`, and
`IgnoreWriteConflicts = "false"`. It adds no bounds on router, shard, key,
transaction, or timestamp sets. There is no reference TLAPS proof and no
proof-completion task.

Bounded TLC checks of the pinned model using `SPECIFICATION Spec` found no
violation: a two-router,
two-shard, two-key, two-transaction model with read timestamps `{1,3}` and
`MaxOpsPerTxn = 1` explored 62,708 distinct states; a three-transaction
simulation with read timestamps `{1,2,3,4,5}` and `MaxOpsPerTxn = 4`
completed 10,000 traces at depth limit 100 with seed `20260913`.
The write/read/write execution (11 states), prepare-blocking control, and
late-commit execution (35 states) also passed their targeted checks, as did
the hand-written isolation examples. These checks used TLC revision `867aefb`,
at most two workers and a 512 MiB heap. They provide bounded evidence for the
task; the complete theorem remains unproved.

Regenerate the task and module suite with:

```sh
uv run python -m dataset.proof_from_scratch.generate --filter /MongoDB/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
```

The pinned repository has no repository-wide license file. `ClientCentric.tla`
identifies its BSD-2-Clause source; see the MongoDB entry in `NOTICE` and
`LICENSES/tla-ci-BSD-2-Clause.txt`.
