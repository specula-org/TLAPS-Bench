--------------------- MODULE StorageReadHistoryAlgebra ---------------------
EXTENDS StorageHistoryFidelity

ExternalReadAt(h,i) ==
  /\ i \in DOMAIN h /\ h[i].op="read"
  /\ ~\E j \in DOMAIN h : j<i /\ h[j].op="write" /\ h[j].key=h[i].key

HistoryOpShape ==
  \A n \in Node, t \in MTxId : \A i \in DOMAIN history[n][t] :
    /\ {"op","key","value"} \subseteq DOMAIN history[n][t][i]
    /\ history[n][t][i].op \in {"read","write"}
    /\ history[n][t][i].key \in Keys
    /\ history[n][t][i].value \in Values \cup {NoValue}

THEOREM HistoryOpShapeInitial == HistoryInit => HistoryOpShape
BY SMT DEF HistoryInit, HistoryOpShape

THEOREM HistoryOpShapeStep ==
  HistoryShape /\ HistoryOpShape /\ [HistoryNext]_historyVars => HistoryOpShape'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF HistoryShape, HistoryOpShape, HistoryNext, HistoryEpochNext, ObservedOperations,
       ObserveRead, ObserveWrite, ObserveRemove, ReadOp, WriteOp, historyVars

THEOREM FullHistoryOpShape == HistorySpec => []HistoryOpShape
BY FullHistoryShape, HistoryOpShapeInitial, HistoryOpShapeStep, PTL DEF HistorySpec

THEOREM AppendPreservesOldExternalReads ==
  ASSUME NEW h, NEW e, NEW i \in DOMAIN h, IsSeq(h)
  PROVE ExternalReadAt(Append(h,e),i) <=> ExternalReadAt(h,i)
BY SMT, AppendEntries, SequenceDomain DEF ExternalReadAt

THEOREM AppendedReadExternal ==
  ASSUME NEW h, NEW k, NEW v, IsSeq(h)
  PROVE ExternalReadAt(Append(h,ReadOp(k,v)),Len(h)+1) <=> k \notin HistoryWriteKeys(h)
BY SMT, AppendEntries, SequenceDomain DEF ExternalReadAt, HistoryWriteKeys, ReadOp

THEOREM AppendedWriteNotRead ==
  ASSUME NEW h, NEW k, NEW v, IsSeq(h)
  PROVE ~ExternalReadAt(Append(h,WriteOp(k,v)),Len(h)+1)
BY SMT, AppendEntries DEF ExternalReadAt, WriteOp

ExternalValues(h,V) ==
  \A i \in DOMAIN h : ExternalReadAt(h,i) => h[i].value = V[h[i].key]
ExternalSafe(h,S) ==
  \A i \in DOMAIN h : ExternalReadAt(h,i) => h[i].key \in S

THEOREM EmptyExternal ==
  ASSUME NEW V, NEW S
  PROVE ExternalValues(<<>>,V) /\ ExternalSafe(<<>>,S)
BY SMT DEF ExternalValues, ExternalSafe

THEOREM ExternalReadAppend ==
  ASSUME NEW h, NEW k, NEW v, NEW V, NEW S, IsSeq(h),
         ExternalValues(h,V), ExternalSafe(h,S),
         k \notin HistoryWriteKeys(h) => (v=V[k] /\ k \in S)
  PROVE ExternalValues(Append(h,ReadOp(k,v)),V) /\ ExternalSafe(Append(h,ReadOp(k,v)),S)
BY SMTT(20), AppendPreservesOldExternalReads, AppendedReadExternal, AppendEntries, SequenceDomain
   DEF ExternalValues, ExternalSafe, ReadOp

THEOREM ExternalWriteAppend ==
  ASSUME NEW h, NEW k, NEW v, NEW V, NEW S, IsSeq(h),
         ExternalValues(h,V), ExternalSafe(h,S)
  PROVE ExternalValues(Append(h,WriteOp(k,v)),V) /\ ExternalSafe(Append(h,WriteOp(k,v)),S)
BY SMTT(20), AppendPreservesOldExternalReads, AppendedWriteNotRead, AppendEntries, SequenceDomain
   DEF ExternalValues, ExternalSafe

THEOREM ExternalTransport ==
  ASSUME NEW h, NEW V, NEW S, NEW V2, NEW S2,
         ExternalValues(h,V), ExternalSafe(h,S), S \subseteq S2,
         \A k \in S : V2[k]=V[k]
  PROVE ExternalValues(h,V2) /\ ExternalSafe(h,S2)
BY SMT DEF ExternalValues, ExternalSafe
=============================================================================
