------------------------- MODULE StorageLocalHistory -------------------------
EXTENDS StorageReadHistoryAlgebra

LocalReadWitness(h,i) ==
  \E j \in DOMAIN h :
    /\ j<i /\ h[j].op="write" /\ h[j].key=h[i].key /\ h[j].value=h[i].value
    /\ \A p \in DOMAIN h : (j<p /\ p<i) => ~(h[p].op="write" /\ h[p].key=h[i].key)
LocalReads(h) ==
  \A i \in DOMAIN h : (h[i].op="read" /\ ~ExternalReadAt(h,i)) => LocalReadWitness(h,i)
LocalHistoryCorrect == \A n \in Node, t \in MTxId : LocalReads(history[n][t])

THEOREM AppendLocalWitness ==
  ASSUME NEW h, NEW e, NEW i \in DOMAIN h, IsSeq(h), LocalReadWitness(h,i)
  PROVE LocalReadWitness(Append(h,e),i)
<1>1. PICK j \in DOMAIN h :
        /\ j<i /\ h[j].op="write" /\ h[j].key=h[i].key /\ h[j].value=h[i].value
        /\ \A p \in DOMAIN h : (j<p /\ p<i) => ~(h[p].op="write" /\ h[p].key=h[i].key)
  BY SMT DEF LocalReadWitness
<1> QED BY SMT, <1>1, AppendEntries, SequenceDomain DEF LocalReadWitness

THEOREM LastWriteBecomesLocalRead ==
  ASSUME NEW h, NEW k, NEW v, NEW j, IsSeq(h), LastWrite(h,k,j), h[j].value=v
  PROVE LocalReadWitness(Append(h,ReadOp(k,v)),Len(h)+1)
BY SMT, AppendEntries, SequenceDomain DEF LastWrite, LocalReadWitness, ReadOp

THEOREM AppendReadLocal ==
  ASSUME NEW h, NEW k, NEW v, IsSeq(h), LocalReads(h),
         k \in HistoryWriteKeys(h) => \E j \in DOMAIN h : LastWrite(h,k,j) /\ h[j].value=v
  PROVE LocalReads(Append(h,ReadOp(k,v)))
BY SMTT(20), AppendLocalWitness, AppendPreservesOldExternalReads,
   LastWriteBecomesLocalRead, AppendedReadExternal, AppendEntries, SequenceDomain
   DEF LocalReads

THEOREM AppendWriteLocal ==
  ASSUME NEW h, NEW k, NEW v, IsSeq(h), LocalReads(h)
  PROVE LocalReads(Append(h,WriteOp(k,v)))
BY SMTT(20), AppendLocalWitness, AppendPreservesOldExternalReads, AppendEntries, SequenceDomain
   DEF LocalReads, WriteOp

THEOREM LocalHistoryInitial == HistoryInit => LocalHistoryCorrect
BY SMT DEF HistoryInit, LocalHistoryCorrect, LocalReads

THEOREM ObservedReadLocal ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, HistoryShape, HistoryFidelity, LocalHistoryCorrect, ObserveRead(n,t,k,v)
  PROVE LocalHistoryCorrect'
<1>1. (txnStatus'[n][t] \in {STATUS_OK,STATUS_NOTFOUND} /\ k \in HistoryWriteKeys(history[n][t])) =>
        \E j \in DOMAIN history[n][t] : LastWrite(history[n][t],k,j) /\ history[n][t][j].value=v
  BY SMT, AcceptedReadSeesOwnWrite
     DEF HistoryFidelity, HistoryState, ObserveRead, TransactionRead, AcceptedRead, ActiveTransactions
<1> QED BY SMT, <1>1, AppendReadLocal
   DEF HistoryShape, LocalHistoryCorrect, ObserveRead

THEOREM ObservedMutationLocal ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         HistoryShape, LocalHistoryCorrect, ObserveWrite(n,t,k,v) \/ ObserveRemove(n,t,k)
  PROVE LocalHistoryCorrect'
BY SMT, AppendWriteLocal DEF HistoryShape, LocalHistoryCorrect, ObserveWrite, ObserveRemove

THEOREM LocalHistoryStep ==
  Inv /\ HistoryShape /\ HistoryFidelity /\ LocalHistoryCorrect /\ [HistoryNext]_historyVars => LocalHistoryCorrect'
BY SMT, ObservedReadLocal, ObservedMutationLocal
   DEF HistoryNext, HistoryEpochNext, ObservedOperations, historyVars, LocalHistoryCorrect

THEOREM FullLocalHistoryCorrect == HistorySpec => []LocalHistoryCorrect
BY HistoryBehaviorProjection, FullNextShape, FullHistoryShape, FullHistoryFidelity,
   LocalHistoryInitial, LocalHistoryStep, PTL DEF HistorySpec, Spec
=============================================================================
