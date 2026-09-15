---- MODULE PaxosHistVar ----
EXTENDS PaxosHistVarDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariant == Spec => []Inv
\* BEGIN AGENT PROOF Paxos/PaxosHistVar_Invariant.tla
PROOF OMITTED
\* END AGENT PROOF Paxos/PaxosHistVar_Invariant.tla

THEOREM Consistent == Spec => []Consistency
\* BEGIN AGENT PROOF Paxos/PaxosHistVar_Consistent.tla
PROOF OMITTED
\* END AGENT PROOF Paxos/PaxosHistVar_Consistent.tla
====
