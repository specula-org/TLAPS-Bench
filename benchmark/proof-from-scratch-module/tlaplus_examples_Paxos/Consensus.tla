---- MODULE Consensus ----
EXTENDS ConsensusDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariance == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_Paxos/Consensus_Invariance.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Paxos/Consensus_Invariance.tla

THEOREM LivenessTheorem == LiveSpec =>  Success
\* BEGIN AGENT PROOF tlaplus_examples_Paxos/Consensus_LivenessTheorem.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Paxos/Consensus_LivenessTheorem.tla
====
