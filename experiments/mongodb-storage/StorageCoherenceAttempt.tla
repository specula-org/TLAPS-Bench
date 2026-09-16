----------------------- MODULE StorageCoherenceAttempt -----------------------
EXTENDS StorageSafety, StorageLifecycle

\* Stronger candidate. The final preservation proof below is an ATTEMPT,
\* not a checked theorem. This module is excluded from claimed-proof replay.
ExternalCoherence ==
  \A n \in Node : \A t \in ActiveTransactions(n) :
    (~mtxnSnapshots[n][t].aborted /\ ~mtxnSnapshots[n][t].prepared) =>
      \A k \in Keys :
        (k \notin mtxnSnapshots[n][t].writeSet /\ ~PrepareConflict(n,t,k)) =>
          TxnRead(n,t,k) = SnapshotRead(n,k,mtxnSnapshots[n][t].ts).value

THEOREM ExternalCoherenceInit == Init => ExternalCoherence
BY SMT DEF Init, ExternalCoherence, ActiveTransactions

THEOREM PreparedCommitCoherenceAttempt ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         Inv, Lifecycle, PrepareModeInvariant, ExternalCoherence,
         CommitPreparedTransaction(n,t,ts,dts)
  PROVE ExternalCoherence'
BY SMTT(30) DEF Inv, SnapshotShape, WriterExclusion, Lifecycle,
  PrepareModeInvariant, ExternalCoherence, CommitPreparedTransaction,
  PreparedTransactions, ActiveTransactions, PrepareConflict, SnapshotUpdatedKeys,
  TxnRead, SnapshotRead, CommitTxnToLogWithDurable, CommitLogEntry
=============================================================================
