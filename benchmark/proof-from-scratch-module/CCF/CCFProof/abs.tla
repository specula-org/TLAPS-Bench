---- MODULE abs ----

EXTENDS Sequences, SequencesExt, Naturals, FiniteSets, Relation

CONSTANT Servers
ASSUME FiniteServersAssumption == IsFiniteSet(Servers)

CONSTANT Terms
ASSUME OrderedTermsAssumption == /\ IsStrictlyTotallyOrderedUnder(<, Terms) 
       /\ \E min \in Terms : \A t \in Terms : min <= t

CONSTANT StartTerm
ASSUME StartTermAssumption == /\ StartTerm \in Terms
       /\ \A t \in Terms : StartTerm <= t

VARIABLE cLogs

====
