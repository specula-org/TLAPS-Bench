------------ MODULE AtomicBakeryWithoutSMTDefs ----------------------------

EXTENDS AtomicBakeryWithoutSMTModel

MutualExclusion == \A i,j \in P : (i # j) => ~ /\ pc[i] = "p7"
                                               /\ pc[j] = "p7"

=============================================================================
