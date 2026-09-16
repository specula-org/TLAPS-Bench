------------------------- MODULE StorageEpochSafety -------------------------
EXTENDS StorageCoherence, StorageVersionOrder

SuccessfulExternalReads ==
  \A n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} :
    (AcceptedRead(n,t,k,v) /\ k \notin mtxnSnapshots[n][t].writeSet)
      => v = SnapshotRead(n,k,mtxnSnapshots[n][t].ts).value

THEOREM CoherentReadResponse == ActiveSnapshotCoherence => SuccessfulExternalReads
BY SMT DEF ActiveSnapshotCoherence, SuccessfulExternalReads, AcceptedRead,
           TransactionRead, ActiveTransactions

THEOREM EpochSuccessfulExternalReads == EpochSpec => [][SuccessfulExternalReads]_vars
BY EpochActiveSnapshotCoherence, CoherentReadResponse, PTL

THEOREM EpochStorageSafety == EpochSpec =>
  /\ []PreparedProvenance
  /\ []CommitProvenance
  /\ []PreparedOrder
  /\ []FreshWrites
  /\ []PerKeyStrictOrder
  /\ []ActiveSnapshotCoherence
  /\ [][SuccessfulExternalReads]_vars
BY EpochPreparedProvenance, EpochCommitProvenance, EpochPreparedOrder,
   EpochFreshWrites, EpochPerKeyStrictOrder, EpochActiveSnapshotCoherence,
   EpochSuccessfulExternalReads, PTL
=============================================================================
