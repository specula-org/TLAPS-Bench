---- MODULE abs ----

EXTENDS Sequences, SequencesExt, Naturals, FiniteSets, Relation

CONSTANT Servers
ASSUME IsFiniteSet(Servers)

CONSTANT Terms
ASSUME /\ IsStrictlyTotallyOrderedUnder(<, Terms) 
       /\ \E min \in Terms : \A t \in Terms : min <= t

CONSTANT StartTerm
ASSUME /\ StartTerm \in Terms
       /\ \A t \in Terms : StartTerm <= t

VARIABLE cLogs

====
