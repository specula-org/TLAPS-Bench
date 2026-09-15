---- MODULE Paxos ----
EXTENDS PaxosDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariant == Spec => []Inv
\* BEGIN AGENT PROOF Paxos/Paxos_Invariant.tla
PROOF OMITTED
\* END AGENT PROOF Paxos/Paxos_Invariant.tla

THEOREM Consistent == Spec => []Consistency
\* BEGIN AGENT PROOF Paxos/Paxos_Consistent.tla
PROOF OMITTED
\* END AGENT PROOF Paxos/Paxos_Consistent.tla

THEOREM Refinement == Spec => C!Spec
\* BEGIN AGENT PROOF Paxos/Paxos_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF Paxos/Paxos_Refinement.tla
====
