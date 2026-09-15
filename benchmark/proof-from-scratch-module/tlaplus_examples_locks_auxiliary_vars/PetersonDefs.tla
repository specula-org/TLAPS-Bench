------------------------------- MODULE PetersonDefs -------------------------------

EXTENDS PetersonModel

lockcs(i) ==
  pc[i] \in {"cs", "a4"}
Inv ==
  /\ \A p \in ProcSet : c[p] <=> pc[p] \in {"a2", "a3", "cs", "a4"}
  /\ \A p \in ProcSet : pc[p] \in {"cs", "a4"} 
      => (turn = p \/ pc[Other(p)] \in {"a0", "a1", "a2"})
  /\ \A i, j \in ProcSet: (i # j) => ~(lockcs(i) /\ lockcs(j))

pc_translation(label) ==
  CASE (label = "a0") -> "l0"
    [] (label \in {"a1", "a2", "a3"}) -> "l1"
    [] (label \in {"cs"}) -> "cs"
    [] (label \in {"a4"}) -> "l2"

lock_translation == IF \E p \in ProcSet : pc[p] \in {"cs", "a4"} THEN 0 ELSE 1

L == INSTANCE Lock
     WITH pc <- [p \in ProcSet |-> pc_translation(pc[p])], 
     lock <- lock_translation

===============================================================================
