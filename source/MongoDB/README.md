# MongoDB distributed transactions

Source: [mongodb-labs/vldb25-dist-txns](https://github.com/mongodb-labs/vldb25-dist-txns/tree/74526c1201109405172eb845413154f547a815ee),
the artifact for [Design and Modular Verification of Distributed Transactions in MongoDB](https://www.vldb.org/pvldb/vol18/p5045-schultz.pdf).
`Storage.tla` and `ClientCentric.tla` are copied unchanged.
`MultiShardTxn.tla` retains its protocol actions and uses the local
`IdentitySnapshotIsolation.tla` for the snapshot-isolation predicate.
`Util.tla` inlines the inner set in `PermSeqs`: this preserves
its permutation values and avoids an incorrect recursive binding when TLAPM
expands it through `INSTANCE`. `upstream.json` records the upstream commit
and hashes separately from the local repair hash.

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
on timestamp values or cardinality bound on any parameter set.
`NoValueIsNotTransaction` additionally requires `NoValue \notin TxId`: the
initial-value sentinel cannot be a transaction's write identifier. This adds a
parameter restriction, consistent with `Storage.TransactionWrite` using the
transaction ID to identify a write's origin. There is no reference TLAPS proof
and no proof-completion task.

## Snapshot positions and transaction identity

`SnapshotTransactions` retains `[id |-> tid, ops |-> ops[tid]]` for every
nonempty observed history. Empty histories contribute no reads or writes and
are omitted; distinct nonempty histories with equal contents retain their IDs.
The parameter sets remain unbounded. The predicate requires the observed
transaction set to be finite, which is a proof obligation for reachable finite
prefixes, not a new finiteness assumption on `TxId`, `Router`, `Shard`, or `Keys`.

`IdentitySnapshotIsolation` orders these records and indexes states by their
execution positions. Equal payloads at two positions stay separate. Each
transaction chooses one earlier snapshot, and its reads are evaluated in
operation order with its preceding local writes. `NoConf` checks the write sets
of intervening transactions, including writes that restore a previous value.
This expresses the Complete and NoConflict requirements in
[the protocol paper, section 2](https://www.vldb.org/pvldb/vol18/p5045-schultz.pdf#page=3).
It does not replace snapshot isolation with serializability: write skew remains
allowed.

This is a substantive correction of the target's predicate, not an equivalent
rewrite of the old `CC!SnapshotIsolation(InitialState, Range(ops))`. The old
predicate loses transaction identity and locates repeated state contents with
an arbitrary `Index` choice. A four-transaction, 42-step protocol trace with
`NoValue = 100` and `100 \in TxId` passes `Spec` and `SingleWritePerKey`, but the
old predicate fails under a consistent last-occurrence choice. The positional
predicate accepts that history. The wrapper separately excludes this sentinel
collision; the predicate regression exercises the base protocol without that
wrapper premise so the premise cannot hide a defective predicate.

`tests/dataset/test_mongodb_snapshot_semantics.py` checks source and generated
contexts, 19 positive/negative semantic controls, the reachable 43-state
witness and old-predicate failure, and sentinel acceptance/rejection. A TLAPS
check covers the initial empty-history mapping and preservation of distinct
IDs without bounding the parameter sets. These are regression checks, not a
complete proof of `SnapshotIsolationCorrect`. Historical results retain their
original input definitions.

## Earlier bounded validation

The following checks predate the positional-predicate correction and are
retained as historical evidence for the original input.

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

The `PermSeqs` regression in `tests/dataset/test_proof_context_compatibility.py`
checks the recursive-function identity through `INSTANCE` with TLAPS and compares
its values to all bijections for every subset of a four-element set with TLC.

Regenerate the task and module suite with:

```sh
uv run python -m dataset.proof_from_scratch.generate --filter /MongoDB/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
```

The pinned repository has no repository-wide license file. `ClientCentric.tla`
identifies its BSD-2-Clause source; see the MongoDB entry in `NOTICE` and
`LICENSES/tla-ci-BSD-2-Clause.txt`.
