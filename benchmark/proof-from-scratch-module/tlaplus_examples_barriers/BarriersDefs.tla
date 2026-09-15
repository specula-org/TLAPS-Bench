------------------------------- MODULE BarriersDefs -------------------------------

EXTENDS BarriersModel

TypeOK ==
  /\ lock \in {0, 1}
  /\ gate_1 \in Nat
  /\ gate_2 \in Nat
  /\ rdv \in Int
  /\ pc \in [ProcSet -> {"a0", "a1", "a2", "a3", "a4", "a5", "a6", 
            "a7", "a8", "a9", "a10", "a11", "a12"}]

rdvsection(p) ==
  pc[p] \in {"a3", "a4", "a5", "a6", "a7", "a8"}
ProcsInRdv ==
  {p \in ProcSet : rdvsection(p)}
  
barrier1(p) ==
  pc[p] \in {"a0", "a1", "a2", "a3", "a4", "a5", "a6"}
ProcsInB1 ==
  {p \in ProcSet : barrier1(p)}
  
barrier2(p) ==
  pc[p] \in {"a7", "a8", "a9", "a10", "a11", "a12"}
ProcsInB2 ==
  {p \in ProcSet : barrier2(p)}

Inv == 
  
  /\ gate_1 \in 0..N
  /\ gate_2 \in 0..N
  
  /\ rdv = Cardinality(ProcsInRdv) 

  /\ gate_1 > 0 => \E p \in ProcSet : pc[p] \in {"a5", "a6"}
  /\ gate_2 > 0 => \E p \in ProcSet : pc[p] \in {"a11", "a12"}
  
  /\ (gate_1 = 0) \/ (gate_2 = 0)

  /\ (\E p \in ProcSet: pc[p] \in {"a0", "a1", "a2", "a3", "a4"})
      => ~(\E p \in ProcSet: pc[p] \in {"a7", "a8", "a9", "a10"})
  
  /\ (\E p \in ProcSet: pc[p] \in {"a7", "a8", "a9", "a10"})
      => ~(\E p \in ProcSet: pc[p] \in {"a0", "a1", "a2", "a3", "a4"})

  /\ gate_1 =< Cardinality(ProcsInB1)
  
  /\ (\E p \in ProcSet: pc[p] \in {"a0", "a1", "a2", "a3", "a4"})
      => gate_1 = 0

  /\ \A p \in ProcSet: pc[p] = "a4" => (
          /\ rdv = N
          /\ \A q \in ProcSet : (p # q) => pc[q] = "a6"
     )

  /\ gate_2 =< Cardinality(ProcsInB2)
  
  /\ (\E p \in ProcSet: pc[p] \in{"a7", "a8", "a9", "a10"})
      => gate_2 = 0

  /\ \A p \in ProcSet: pc[p] = "a10" => (
          /\ rdv = 0
          /\ \A q \in ProcSet : (p # q) => pc[q] = "a12"
     )

FlushInv ==
  /\ gate_1 > 0 => gate_1 = Cardinality(ProcsInB1)
  /\ gate_2 > 0 => gate_2 = Cardinality(ProcsInB2)

pc_translation(self) ==
  IF pc[self] \in {"a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9", "a10"}
    THEN "b1"
  ELSE IF pc[self] = "a0" 
    THEN "b0"
  ELSE IF gate_2 > 0
    THEN "b0"
  ELSE "b1"

B == INSTANCE Barrier WITH pc <- [p \in ProcSet |-> pc_translation(p)]

===============================================================================
