---- MODULE Voting ----
EXTENDS VotingDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM  Invariance  ==  Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_Invariance.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_Invariance.tla

THEOREM  Implementation  ==  Spec  => C!Spec
\* BEGIN AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_Implementation.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_Implementation.tla
====
