---- MODULE Voting ----
EXTENDS VotingDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM QuorumNonEmpty == \A Q \in Quorum : Q # {}
\* BEGIN AGENT PROOF tlaplus_examples_Paxos/Voting_QuorumNonEmpty.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Paxos/Voting_QuorumNonEmpty.tla

THEOREM Spec => C!Spec
\* BEGIN AGENT PROOF tlaplus_examples_Paxos/Voting_C_Spec.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Paxos/Voting_C_Spec.tla
====
