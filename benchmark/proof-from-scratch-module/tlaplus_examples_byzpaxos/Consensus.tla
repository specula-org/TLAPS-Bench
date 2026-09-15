---- MODULE Consensus ----
EXTENDS ConsensusDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariance == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/Consensus_Invariance.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/Consensus_Invariance.tla

THEOREM Liveness == LiveSpec => Success
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/Consensus_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/Consensus_Liveness.tla

THEOREM LiveSpecEquals ==
          LiveSpec <=> Spec /\ ([]<><<Next>>_vars \/ []<>(chosen # {}))
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/Consensus_LiveSpecEquals.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/Consensus_LiveSpecEquals.tla
====
