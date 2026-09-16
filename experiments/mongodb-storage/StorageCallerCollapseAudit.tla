--------------------- MODULE StorageCallerCollapseAudit ---------------------
EXTENDS StorageCallerCollapseSI

\* An additional bounded audit of the exact counterexample, not a changed SI target.
\* The original Index and ClientCentric definitions are never overridden.
ExpectedHistories == {
  <<WriteOp(X,A),WriteOp(Y,A)>>,
  <<ReadOp(Y,A),ReadOp(X,NoValue),WriteOp(X,B),WriteOp(Z,B)>>,
  <<WriteOp(X,NoValue)>>,
  <<ReadOp(Z,B),ReadOp(X,NoValue)>> }

RepresentativeMaps(e) ==
  {f \in [SeqToSet(CC!executionStates(e)) -> 1..Len(e)] :
     \A s \in DOMAIN f : e[f[s]].parentState = s}

\* Overapproximate every legitimate CHOOSE selection for equal state values.
\* Operation Index remains the exact original operator (all ops here are distinct).
ChoiceComplete(e,h,s,f) ==
  /\ s \in SeqToSet(CC!executionStates(e))
  /\ f[s] <= f[CC!parentState(e,h)]
  /\ \A op \in SeqToSet(h) :
       \/ op.op = "write"
       \/ s[op.key] = op.value
       \/ \E w \in SeqToSet(h) :
            /\ w.op = "write" /\ w.key = op.key /\ w.value = op.value
            /\ CC!earlierInTransaction(h,w,op)

AllRepresentativeChoicesFail ==
  \A e \in CC!executions([k \in Keys |-> NoValue],ExpectedHistories) :
    \A f \in RepresentativeMaps(e) :
      ~\E sb,sr \in SeqToSet(CC!executionStates(e)) :
        /\ ChoiceComplete(e,history[N][B],sb,f)
        /\ ChoiceComplete(e,history[N][R],sr,f)

\* Check original CHOOSE is included by the overapproximation at this instance.
OriginalChoiceIncluded ==
  \A e \in CC!executions([k \in Keys |-> NoValue],ExpectedHistories) :
    LET f == [s \in SeqToSet(CC!executionStates(e)) |-> Index(CC!executionStates(e),s)] IN
      /\ f \in RepresentativeMaps(e)
      /\ \A h \in ExpectedHistories : \A s \in SeqToSet(CC!executionStates(e)) :
           CC!Complete(e,h,s) = ChoiceComplete(e,h,s,f)

AuditFinal == pc = 20 =>
  /\ LegacyCommittedHistories(N) = ExpectedHistories
  /\ Cardinality(CommittedTransactions(N,mtxnSnapshots)) = 5
  /\ Cardinality(LegacyCommittedHistories(N)) = 4
  /\ Cardinality(CommittedHistories(N)) = 5
  /\ history[N][D1] = history[N][D2]
  /\ Cardinality(CC!executions([k \in Keys |-> NoValue],ExpectedHistories)) = 24
  /\ AllRepresentativeChoicesFail
  /\ OriginalChoiceIncluded
  /\ ~LegacyFullSI
  /\ FullSI
=============================================================================
