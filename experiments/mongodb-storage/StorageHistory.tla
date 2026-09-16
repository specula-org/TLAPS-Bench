--------------------------- MODULE StorageHistory ---------------------------
EXTENDS Storage

ASSUME RC = "snapshot"
ASSUME Timestamps \subseteq Nat
ASSUME NoValue \notin MTxId

VARIABLE history
historyVars == <<vars, history>>
CC == INSTANCE ClientCentric WITH Keys <- Keys, Values <- Values \cup {NoValue}
IdentityCC == INSTANCE IdentitySnapshotIsolation WITH Keys <- Keys, Values <- Values \cup {NoValue}

ReadOp(k,v) == [op |-> "read", key |-> k, value |-> v]
WriteOp(k,v) == [op |-> "write", key |-> k, value |-> v]

HistoryInit ==
  /\ Init
  /\ history = [n \in Node |-> [t \in MTxId |-> <<>>]]

ObserveRead(n,t,k,v) ==
  /\ TransactionRead(n,t,k,v)
  /\ history' = IF txnStatus'[n][t] \in {STATUS_OK, STATUS_NOTFOUND}
                THEN [history EXCEPT ![n][t] = Append(@,ReadOp(k,v))]
                ELSE history

ObserveWrite(n,t,k,v) ==
  /\ TransactionWrite(n,t,k,v,"false")
  /\ history' = IF txnStatus'[n][t] = STATUS_OK
                THEN [history EXCEPT ![n][t] = Append(@,WriteOp(k,v))]
                ELSE history

ObserveRemove(n,t,k) ==
  /\ TransactionRemove(n,t,k)
  /\ history' = IF txnStatus'[n][t] = STATUS_OK
                THEN [history EXCEPT ![n][t] = Append(@,WriteOp(k,NoValue))]
                ELSE history

QuietEpochNext ==
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps, ip \in IgnorePrepareOptions : StartTransaction(n,t,ts,RC,ip)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : PrepareTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : CommitTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts, dts \in Timestamps : CommitPreparedTransaction(n,t,ts,dts)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)

ObservedOperations ==
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : ObserveRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values : ObserveWrite(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys : ObserveRemove(n,t,k)

HistoryEpochNext == ObservedOperations \/ (QuietEpochNext /\ UNCHANGED history)
HistoryNext == HistoryEpochNext \/ ((\E n \in Node : RollbackToStable(n)) /\ UNCHANGED history)
HistorySpec == HistoryInit /\ [][HistoryNext]_historyVars
HistoryEpochSpec == HistoryInit /\ [][HistoryEpochNext]_historyVars

SingleWritePerKey ==
  \A n \in Node, t \in MTxId : \A i,j \in DOMAIN history[n][t] :
    (i < j /\ history[n][t][i].op = "write" /\ history[n][t][j].op = "write")
      => history[n][t][i].key # history[n][t][j].key

CommittedHistories(n) ==
  {[id |-> t, ops |-> history[n][t]] : t \in CommittedTransactions(n,mtxnSnapshots)}
FullSI == \A n \in Node :
  IdentityCC!SnapshotIsolation([k \in Keys |-> NoValue], CommittedHistories(n))

\* Preserve the refuted representation for historical negative controls.
LegacyCommittedHistories(n) == {history[n][t] : t \in CommittedTransactions(n,mtxnSnapshots)}
LegacyFullSI == \A n \in Node :
  CC!SnapshotIsolation([k \in Keys |-> NoValue], LegacyCommittedHistories(n))
LegacyFullSITarget == (HistorySpec /\ []SingleWritePerKey) => []LegacyFullSI
LegacyEpochSITarget == (HistoryEpochSpec /\ []SingleWritePerKey) => []LegacyFullSI

\* Identity-aware targets, NOT theorems: no SI implication has a TLAPS proof.
FullSITarget == (HistorySpec /\ []SingleWritePerKey) => []FullSI
EpochSITarget == (HistoryEpochSpec /\ []SingleWritePerKey) => []FullSI

\* Only finite TLC exploration uses these two operators.
CheckedEpochNext == HistoryEpochNext /\ SingleWritePerKey'
HistoryBound == \A n \in Node, t \in MTxId : Len(history[n][t]) <= 2
=============================================================================
