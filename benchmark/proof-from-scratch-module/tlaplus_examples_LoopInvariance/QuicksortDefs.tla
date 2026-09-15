----------------------------- MODULE QuicksortDefs -----------------------------

EXTENDS QuicksortModel

PCorrect == (pc = "Done") => 
               /\ seq \in PermsOf(seq0)
               /\ \A p, q \in 1..Len(seq) : p < q => seq[p] =< seq[q] 

=============================================================================

