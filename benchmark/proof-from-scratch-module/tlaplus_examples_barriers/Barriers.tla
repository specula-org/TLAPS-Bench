---- MODULE Barriers ----
EXTENDS BarriersDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariant == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_barriers/Barriers_Invariant.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_barriers/Barriers_Invariant.tla

THEOREM BarrierExclusion ==
    Inv => \/ ~(\E p \in ProcSet: pc[p] \in {"a0", "a1", "a2", "a3", "a4"})
           \/ ~(\E p \in ProcSet: pc[p] \in {"a7", "a8", "a9", "a10"})
\* BEGIN AGENT PROOF tlaplus_examples_barriers/Barriers_BarrierExclusion.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_barriers/Barriers_BarrierExclusion.tla

THEOREM BarrierExclusion2 ==
    TypeOK /\ Inv => 
      \/ (\A p \in ProcSet: pc[p] \in 
                    {"a5", "a6", "a7", "a8", "a9", "a10", "a11", "a12"})
      \/ (\A p \in ProcSet: pc[p] \in 
                    {"a11", "a12", "a0", "a1", "a2", "a3", "a4", "a5", "a6"})
\* BEGIN AGENT PROOF tlaplus_examples_barriers/Barriers_BarrierExclusion2.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_barriers/Barriers_BarrierExclusion2.tla

THEOREM FlushInvariant == Spec => []FlushInv
\* BEGIN AGENT PROOF tlaplus_examples_barriers/Barriers_FlushInvariant.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_barriers/Barriers_FlushInvariant.tla

THEOREM Spec => B!Spec
\* BEGIN AGENT PROOF tlaplus_examples_barriers/Barriers_B_Spec.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_barriers/Barriers_B_Spec.tla
====
