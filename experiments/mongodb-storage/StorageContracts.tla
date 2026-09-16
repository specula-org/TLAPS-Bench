------------------------- MODULE StorageContracts -------------------------
EXTENDS Storage, TLAPS

WriterExclusion ==
  \A n \in Node : \A a, b \in ActiveTransactions(n) :
    a # b => mtxnSnapshots[n][a].writeSet \cap mtxnSnapshots[n][b].writeSet = {}

SnapshotShape ==
  /\ DOMAIN mtxnSnapshots = Node
  /\ \A n \in Node :
       /\ DOMAIN mtxnSnapshots[n] = MTxId
       /\ \A t \in MTxId :
            /\ "active" \in DOMAIN mtxnSnapshots[n][t]
            /\ mtxnSnapshots[n][t].active \in BOOLEAN
            /\ (mtxnSnapshots[n][t].active =>
                  "writeSet" \in DOMAIN mtxnSnapshots[n][t])

Inv == SnapshotShape /\ WriterExclusion

Spec == Init /\ [][Next]_vars

THEOREM WriterExclusionInit == Init => Inv
BY SMT DEF Init, Inv, SnapshotShape, WriterExclusion, ActiveTransactions

THEOREM StartPreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW readTs,
         NEW rc, NEW ignorePrepare,
         Inv, StartTransaction(n, tid, readTs, rc, ignorePrepare)
  PROVE Inv'
BY SMT DEF Inv, SnapshotShape, WriterExclusion, StartTransaction, ActiveTransactions, SnapshotKV

THEOREM WritePreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW k \in Keys, NEW v,
         Inv, TransactionWrite(n, tid, k, v, "false")
  PROVE Inv'
<1>1. SnapshotShape'
  BY SMT DEF Inv, SnapshotShape, TransactionWrite, ActiveTransactions
<1>2. \A p \in Node : \A t \in MTxId :
        mtxnSnapshots'[p][t].active = mtxnSnapshots[p][t].active
  BY SMT DEF Inv, SnapshotShape, TransactionWrite
<1>3. \A p \in Node : \A t \in ActiveTransactions(p) :
        \/ mtxnSnapshots'[p][t].writeSet = mtxnSnapshots[p][t].writeSet
        \/ /\ p = n /\ t = tid
           /\ ~WriteConflictExists(n,tid,k)
           /\ mtxnSnapshots'[p][t].writeSet = mtxnSnapshots[p][t].writeSet \cup {k}
  BY SMT DEF Inv, SnapshotShape, TransactionWrite, ActiveTransactions
<1>4. ~WriteConflictExists(n,tid,k) =>
        \A t \in ActiveTransactions(n) \ {tid} : k \notin mtxnSnapshots[n][t].writeSet
  BY SMT DEF TransactionWrite, WriteConflictExists, ActiveTransactions
<1>5. WriterExclusion'
  BY SMT, <1>2, <1>3, <1>4 DEF Inv, WriterExclusion, ActiveTransactions
<1> QED BY SMT, <1>1, <1>5 DEF Inv

THEOREM RemovePreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW k \in Keys,
         Inv, TransactionRemove(n, tid, k)
  PROVE Inv'
<1>1. SnapshotShape'
  BY SMT DEF Inv, SnapshotShape, TransactionRemove, ActiveTransactions
<1>2. \A p \in Node : \A t \in MTxId :
        mtxnSnapshots'[p][t].active = mtxnSnapshots[p][t].active
  BY SMT DEF Inv, SnapshotShape, TransactionRemove
<1>3. \A p \in Node : \A t \in ActiveTransactions(p) :
        \/ mtxnSnapshots'[p][t].writeSet = mtxnSnapshots[p][t].writeSet
        \/ /\ p = n /\ t = tid
           /\ ~WriteConflictExists(n,tid,k)
           /\ mtxnSnapshots'[p][t].writeSet = mtxnSnapshots[p][t].writeSet \cup {k}
  BY SMT DEF Inv, SnapshotShape, TransactionRemove, ActiveTransactions
<1>4. ~WriteConflictExists(n,tid,k) =>
        \A t \in ActiveTransactions(n) \ {tid} : k \notin mtxnSnapshots[n][t].writeSet
  BY SMT DEF TransactionRemove, WriteConflictExists, ActiveTransactions
<1>5. WriterExclusion'
  BY SMT, <1>2, <1>3, <1>4 DEF Inv, WriterExclusion, ActiveTransactions
<1> QED BY SMT, <1>1, <1>5 DEF Inv

THEOREM ReadPreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW k \in Keys, NEW v,
         Inv, TransactionRead(n, tid, k, v)
  PROVE Inv'
BY SMT DEF Inv, SnapshotShape, WriterExclusion, TransactionRead, ActiveTransactions

THEOREM PreparePreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW ts,
         Inv, PrepareTransaction(n, tid, ts)
  PROVE Inv'
BY SMT DEF Inv, SnapshotShape, WriterExclusion, PrepareTransaction, ActiveTransactions

THEOREM CommitPreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW ts,
         Inv, CommitTransaction(n, tid, ts)
  PROVE Inv'
BY SMT DEF Inv, SnapshotShape, WriterExclusion, CommitTransaction, ActiveTransactions

THEOREM PreparedCommitPreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId, NEW ts, NEW dts,
         Inv, CommitPreparedTransaction(n, tid, ts, dts)
  PROVE Inv'
BY SMT DEF Inv, SnapshotShape, WriterExclusion, CommitPreparedTransaction, ActiveTransactions

THEOREM AbortPreservesWriterExclusion ==
  ASSUME NEW n \in Node, NEW tid \in MTxId,
         Inv, AbortTransaction(n, tid)
  PROVE Inv'
BY SMT DEF Inv, SnapshotShape, WriterExclusion, AbortTransaction, ActiveTransactions

THEOREM WriterExclusionStep == Inv /\ [Next]_vars => Inv'
<1>1. ASSUME Inv, Next PROVE Inv'
  BY SMT, <1>1, StartPreservesWriterExclusion, WritePreservesWriterExclusion,
     RemovePreservesWriterExclusion, ReadPreservesWriterExclusion,
     PreparePreservesWriterExclusion, CommitPreservesWriterExclusion,
     PreparedCommitPreservesWriterExclusion, AbortPreservesWriterExclusion
     DEF Next, SetStableTimestamp, SetOldestTimestamp, RollbackToStable,
         Inv, SnapshotShape, WriterExclusion, ActiveTransactions
<1>2. ASSUME Inv, UNCHANGED vars PROVE Inv'
  BY SMT, <1>2 DEF vars, Inv, SnapshotShape, WriterExclusion, ActiveTransactions
<1> QED BY SMT, <1>1, <1>2

THEOREM FullNextWriterExclusion == Spec => []WriterExclusion
<1>1. Init => Inv BY SMT, WriterExclusionInit
<1>2. Inv /\ [Next]_vars => Inv' BY SMT, WriterExclusionStep
<1> QED BY <1>1, <1>2, PTL DEF Spec, Inv
=============================================================================
