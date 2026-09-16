------------------------- MODULE StorageCandidates -------------------------
EXTENDS Storage

CommitAppendOrder ==
  \A n \in Node : \A i, j \in DOMAIN mlog[n] :
    (i < j /\ "data" \in DOMAIN mlog[n][i] /\ "data" \in DOMAIN mlog[n][j])
      => mlog[n][i].ts <= mlog[n][j].ts

WriterExclusion ==
  \A n \in Node : \A a, b \in ActiveTransactions(n) :
    a # b => mtxnSnapshots[n][a].writeSet \cap mtxnSnapshots[n][b].writeSet = {}

ExternalReadCoherence ==
  \A n \in Node : \A t \in ActiveTransactions(n) :
    (~mtxnSnapshots[n][t].aborted /\ ~mtxnSnapshots[n][t].prepared) =>
      \A k \in Keys :
        (k \notin mtxnSnapshots[n][t].writeSet /\ ~PrepareConflict(n,t,k)) =>
          TxnRead(n,t,k) = SnapshotRead(n,k,mtxnSnapshots[n][t].ts).value

\* Diagnostic recovery-free epoch: all full-Next actions except rollback.
\* The unrestricted temporal theorem in StorageContracts uses Storage.Next.
EpochNext ==
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps, ip \in IgnorePrepareOptions : StartTransaction(n,t,ts,RC,ip)
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values : TransactionWrite(n,t,k,v,"false")
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : TransactionRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys : TransactionRemove(n,t,k)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : PrepareTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : CommitTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts, dts \in Timestamps : CommitPreparedTransaction(n,t,ts,dts)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)
\* Continuation falsification candidates; stronger than the original guarded read claim.
StrongReadCoherenceMC ==
  \A n \in Node : \A t \in ActiveTransactions(n) : \A k \in Keys :
    k \notin mtxnSnapshots[n][t].writeSet =>
      TxnRead(n,t,k) = SnapshotRead(n,k,mtxnSnapshots[n][t].ts).value

PreparedLogProvenanceMC ==
  \A n \in Node : \A t \in PreparedTransactions(n) :
    \E i \in DOMAIN mlog[n] :
      /\ "prepare" \in DOMAIN mlog[n][i]
      /\ mlog[n][i].tid = t
      /\ mlog[n][i].ts = mtxnSnapshots[n][t].prepareTs

=============================================================================
