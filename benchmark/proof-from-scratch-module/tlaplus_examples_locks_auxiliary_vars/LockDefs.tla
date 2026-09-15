--------------------------------- MODULE LockDefs ---------------------------------

EXTENDS LockModel

lockcs(i) ==
  pc[i] \in {"cs", "l2"}

LockInv == 
  /\ \A i, j \in ProcSet: (i # j) => ~(lockcs(i) /\ lockcs(j))
  /\ (\E p \in ProcSet: lockcs(p)) => lock = 0

===============================================================================
