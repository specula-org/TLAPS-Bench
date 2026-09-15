------------ MODULE AtomicBakeryDefs ----------------------------

EXTENDS AtomicBakeryModel

MutualExclusion == \A i,j \in P : (i # j) => ~ /\ pc[i] = "cs"
                                               /\ pc[j] = "cs"

=============================================================================

