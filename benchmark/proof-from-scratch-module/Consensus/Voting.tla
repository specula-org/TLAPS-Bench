---- MODULE Voting ----
EXTENDS VotingDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM QuorumNonEmpty == \A Q \in Quorum : Q # {}
\* BEGIN AGENT PROOF Consensus/Voting_QuorumNonEmpty.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/Voting_QuorumNonEmpty.tla

THEOREM AllSafeAtZero == \A v \in Value : SafeAt(0, v)
\* BEGIN AGENT PROOF Consensus/Voting_AllSafeAtZero.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/Voting_AllSafeAtZero.tla

THEOREM ChoosableThm ==
          \A b \in Ballot, v \in Value :
             ChosenAt(b, v) => NoneOtherChoosableAt(b, v)
\* BEGIN AGENT PROOF Consensus/Voting_ChoosableThm.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/Voting_ChoosableThm.tla

THEOREM Invariant == Spec => []Inv
\* BEGIN AGENT PROOF Consensus/Voting_Invariant.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/Voting_Invariant.tla

THEOREM Consistent == Spec => []Consistency
\* BEGIN AGENT PROOF Consensus/Voting_Consistent.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/Voting_Consistent.tla

THEOREM Refinement == Spec => C!Spec
\* BEGIN AGENT PROOF Consensus/Voting_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/Voting_Refinement.tla
====
