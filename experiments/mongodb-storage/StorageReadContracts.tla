----------------------- MODULE StorageReadContracts -----------------------
EXTENDS StorageContracts

StatusShape ==
  /\ DOMAIN txnStatus = Node
  /\ \A n \in Node : DOMAIN txnStatus[n] = MTxId

THEOREM StatusShapeInit == Init => StatusShape
BY SMT DEF Init, StatusShape

THEOREM StatusShapeStep == StatusShape /\ [Next]_vars => StatusShape'
BY SMTT(20) DEF StatusShape, Next, vars, StartTransaction,
  TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
  CommitTransaction, CommitPreparedTransaction, AbortTransaction,
  SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM FullNextStatusShape == Spec => []StatusShape
<1>1. Init => StatusShape BY StatusShapeInit
<1>2. StatusShape /\ [Next]_vars => StatusShape' BY StatusShapeStep
<1> QED BY <1>1, <1>2, PTL DEF Spec

AcceptedRead(n,t,k,v) ==
  /\ TransactionRead(n,t,k,v)
  /\ txnStatus'[n][t] \in {STATUS_OK, STATUS_NOTFOUND}

THEOREM AcceptedReadHasNoPrepareConflict ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         StatusShape, mtxnSnapshots[n][t].ignorePrepare = "false",
         AcceptedRead(n,t,k,v)
  PROVE /\ ~PrepareConflict(n,t,k)
        /\ v = TxnRead(n,t,k)
        /\ (txnStatus'[n][t] = STATUS_NOTFOUND <=> v = NoValue)
BY SMT DEF StatusShape, AcceptedRead, TransactionRead,
           STATUS_OK, STATUS_NOTFOUND, STATUS_PREPARE_CONFLICT

THEOREM AcceptedReadExcludesPreparedWriter ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         StatusShape, mtxnSnapshots[n][t].ignorePrepare = "false",
         AcceptedRead(n,t,k,v)
  PROVE ~\E other \in ActiveTransactions(n) \ {t} :
          /\ mtxnSnapshots[n][other].prepared
          /\ k \in mtxnSnapshots[n][other].writeSet
          /\ mtxnSnapshots[n][other].prepareTs <= mtxnSnapshots[n][t].ts
BY SMT, AcceptedReadHasNoPrepareConflict
   DEF PrepareConflict, SnapshotUpdatedKeys, ActiveTransactions

THEOREM AcceptedReadSeesOwnWrite ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         AcceptedRead(n,t,k,v), k \in mtxnSnapshots[n][t].writeSet
  PROVE v = mtxnSnapshots[n][t].data[k]
BY SMT DEF AcceptedRead, TransactionRead, TxnRead

SafeReadResponses ==
  \A n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} :
    (mtxnSnapshots[n][t].ignorePrepare = "false" /\ AcceptedRead(n,t,k,v)) =>
      /\ ~PrepareConflict(n,t,k)
      /\ (txnStatus'[n][t] = STATUS_NOTFOUND <=> v = NoValue)
      /\ (k \in mtxnSnapshots[n][t].writeSet => v = mtxnSnapshots[n][t].data[k])

THEOREM ReadResponseStep == StatusShape => SafeReadResponses
BY SMT, AcceptedReadHasNoPrepareConflict, AcceptedReadSeesOwnWrite
   DEF SafeReadResponses

THEOREM FullNextReadResponses == Spec => [][SafeReadResponses]_vars
BY FullNextStatusShape, ReadResponseStep, PTL
=============================================================================
