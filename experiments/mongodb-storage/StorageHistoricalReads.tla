------------------------ MODULE StorageHistoricalReads ------------------------
EXTENDS StorageReadStability, StorageReadHistoryAlgebra, StorageCallerHistory

ReadValues(n,t) == [k \in Keys |-> LogRead(mlog[n],k,mtxnSnapshots[n][t].ts)]
ReadSafeKeys(n,t) == {k \in Keys : ~PrepareConflict(n,t,k)}

HistoricalExternalCoherence ==
  \A n \in Node : \A t \in UsedTransactions(n) :
    /\ ExternalValues(history[n][t],ReadValues(n,t))
    /\ ExternalSafe(history[n][t],ReadSafeKeys(n,t))

OldHistoryTransport ==
  \A n \in Node : \A t \in UsedTransactions(n) :
    /\ ExternalValues(history[n][t],ReadValues(n,t)')
    /\ ExternalSafe(history[n][t],ReadSafeKeys(n,t)')

THEOREM HistoricalReadsInitial == HistoryInit => HistoricalExternalCoherence
BY SMT DEF HistoryInit, Init, HistoricalExternalCoherence, UsedTransactions,
           ActiveTransactions, CommittedTransactions

THEOREM TransportOldHistory ==
  HistoricalExternalCoherence /\ SafeReadTransport => OldHistoryTransport
BY SMTT(15)
   DEF HistoricalExternalCoherence, SafeReadTransport, OldHistoryTransport,
       ReadValues, ReadSafeKeys, ExternalValues, ExternalSafe

THEOREM ReadAddsExternalObservation ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, StatusShape, PrepareModeInvariant, ActiveSnapshotCoherence,
         HistoryFidelity, SafeReadTransport, ObserveRead(n,t,k,v),
         txnStatus'[n][t] \in {STATUS_OK,STATUS_NOTFOUND},
         k \notin HistoryWriteKeys(history[n][t])
  PROVE v=ReadValues(n,t)'[k] /\ k \in ReadSafeKeys(n,t)'
<1>1. /\ k \notin mtxnSnapshots[n][t].writeSet
        /\ t \in ActiveTransactions(n)
        /\ ~PrepareConflict(n,t,k)
        /\ v = LogRead(mlog[n],k,mtxnSnapshots[n][t].ts)
  BY SMT, AcceptedReadHasNoPrepareConflict, SnapshotReadValue
     DEF HistoryFidelity, HistoryState, ObserveRead, TransactionRead,
         ActiveSnapshotCoherence, PrepareModeInvariant, AcceptedRead, ActiveTransactions
<1> QED BY SMT, <1>1 DEF SafeReadTransport, UsedTransactions, ReadValues, ReadSafeKeys

THEOREM ObserveReadHistoricalCoherence ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, Lifecycle, StatusShape, PrepareModeInvariant, ActiveSnapshotCoherence,
         HistoryShape, HistoryFidelity, HistoricalExternalCoherence,
         SafeReadTransport, ObserveRead(n,t,k,v)
  PROVE HistoricalExternalCoherence'
<1>1. OldHistoryTransport BY SMT, TransportOldHistory
<1>2. k \notin HistoryWriteKeys(history[n][t]) /\
       txnStatus'[n][t] \in {STATUS_OK,STATUS_NOTFOUND} =>
         v=ReadValues(n,t)'[k] /\ k \in ReadSafeKeys(n,t)'
  BY SMT, ReadAddsExternalObservation
<1> QED BY SMTT(20), <1>1, <1>2, ExternalReadAppend
   DEF HistoricalExternalCoherence, OldHistoryTransport, HistoryShape,
       Inv, SnapshotShape, Lifecycle, ObserveRead, TransactionRead,
       UsedTransactions, CommittedTransactions, ActiveTransactions

THEOREM ObserveWriteHistoricalCoherence ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, Lifecycle, HistoryShape, HistoricalExternalCoherence, SafeReadTransport,
         ObserveWrite(n,t,k,v)
  PROVE HistoricalExternalCoherence'
<1>1. OldHistoryTransport BY SMT, TransportOldHistory
<1> QED BY SMTT(20), <1>1, ExternalWriteAppend
   DEF HistoricalExternalCoherence, OldHistoryTransport, HistoryShape,
       Inv, SnapshotShape, Lifecycle, ObserveWrite,
       TransactionWrite, UsedTransactions, CommittedTransactions, ActiveTransactions

THEOREM ObserveRemoveHistoricalCoherence ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys,
         Inv, Lifecycle, HistoryShape, HistoricalExternalCoherence, SafeReadTransport,
         ObserveRemove(n,t,k)
  PROVE HistoricalExternalCoherence'
<1>1. OldHistoryTransport BY SMT, TransportOldHistory
<1>2. /\ ExternalValues(Append(history[n][t],WriteOp(k,NoValue)),ReadValues(n,t)')
        /\ ExternalSafe(Append(history[n][t],WriteOp(k,NoValue)),ReadSafeKeys(n,t)')
  BY SMT, <1>1, ExternalWriteAppend
     DEF HistoryShape, OldHistoryTransport, ObserveRemove, TransactionRemove, UsedTransactions
<1>3. \A q \in Node : UsedTransactions(q)'=UsedTransactions(q)
  BY SMT DEF Inv, SnapshotShape, Lifecycle, ObserveRemove, TransactionRemove,
             UsedTransactions, CommittedTransactions, ActiveTransactions
<1>4. \A q \in Node : UsedTransactions(q) \subseteq MTxId
  BY SMT DEF UsedTransactions, ActiveTransactions, CommittedTransactions
<1> QED BY SMT, <1>1, <1>2, <1>3, <1>4
   DEF HistoricalExternalCoherence, OldHistoryTransport, HistoryShape, ObserveRemove

THEOREM QuietHistoricalCoherence ==
  Inv /\ Lifecycle /\ HistoryFidelity /\ HistoricalExternalCoherence /\
  SafeReadTransport /\ UNCHANGED history /\
  (QuietEpochNext \/ UNCHANGED vars) => HistoricalExternalCoherence'
<1>1. ASSUME Inv, Lifecycle, HistoryFidelity, HistoricalExternalCoherence,
             SafeReadTransport, UNCHANGED history, QuietEpochNext \/ UNCHANGED vars
      PROVE HistoricalExternalCoherence'
  <2>1. OldHistoryTransport BY SMT, <1>1, TransportOldHistory
  <2> QED BY SMTT(20), <1>1, <2>1, EmptyExternal
     DEF HistoricalExternalCoherence, OldHistoryTransport, HistoryFidelity,
         Inv, SnapshotShape, Lifecycle, UsedTransactions, CommittedTransactions,
         ActiveTransactions, QuietEpochNext, vars, StartTransaction, SnapshotKV,
         PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
         AbortTransaction, SetStableTimestamp, SetOldestTimestamp
<1> QED BY SMT, <1>1

THEOREM HistoricalReadsStep ==
  Inv /\ Lifecycle /\ StatusShape /\ PrepareModeInvariant /\ ActiveSnapshotCoherence /\
  HistoryShape /\ HistoryFidelity /\ HistoricalExternalCoherence /\ SafeReadTransport /\
  [HistoryEpochNext]_historyVars => HistoricalExternalCoherence'
BY SMT, ObserveReadHistoricalCoherence, ObserveWriteHistoricalCoherence, ObserveRemoveHistoricalCoherence,
   QuietHistoricalCoherence DEF HistoryEpochNext, ObservedOperations, historyVars

THEOREM CallerHistoryToFullHistory == CallerHistoryEpochSpec => HistorySpec
BY PTL DEF CallerHistoryEpochSpec, CallerHistoryEpochNext, HistorySpec, HistoryNext

THEOREM HistoricalReadsInduction ==
  Inv /\ Lifecycle /\ StatusShape /\ PrepareModeInvariant /\ ActiveSnapshotCoherence /\
  PrepareShape /\ LogShape /\ TimestampShape /\ TimestampBound /\ CommitIdentity /\
  CommitSnapshot /\ PreparedOrder /\ HistoryShape /\ HistoryFidelity /\
  HistoricalExternalCoherence /\ [CallerHistoryEpochNext]_historyVars
    => HistoricalExternalCoherence'
BY SMT, HistoricalReadsStep, SafeReadTransportStep, HistoryEpochActionProjection
   DEF CallerHistoryEpochNext, CallerEpochNext, historyVars

THEOREM CallerHistoricalExternalCoherence ==
  CallerHistoryEpochSpec => []HistoricalExternalCoherence
BY CallerHistoryProjection, CallerEpochProjection, EpochBehaviorProjection,
   CallerHistoryToFullHistory, FullNextShape, FullNextLifecycle, FullNextStatusShape,
   FullNextPrepareMode, EpochActiveSnapshotCoherence, EpochPrepareShape,
   EpochLogShape, EpochTimestampShape, EpochTimestampBound, EpochCommitIdentity,
   EpochCommitSnapshot, EpochPreparedOrder, FullHistoryShape, FullHistoryFidelity,
   HistoricalReadsInitial, HistoricalReadsInduction, PTL DEF CallerHistoryEpochSpec
=============================================================================
