---- MODULE Voting_proof ----
EXTENDS Voting_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM AllSafeAtZero_T == \A v \in Value : SafeAt(0, v)
\* BEGIN AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_proof_AllSafeAtZero_T.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_proof_AllSafeAtZero_T.tla

THEOREM ChoosableThm_T ==
    \A b \in Ballot, v \in Value : ChosenAt(b, v) => NoneOtherChoosableAt(b, v)
\* BEGIN AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_proof_ChoosableThm_T.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_proof_ChoosableThm_T.tla

THEOREM ShowsSafety_T ==
    Inv => \A Q \in Quorum, b \in Ballot, v \in Value :
              ShowsSafeAt(Q, b, v) => SafeAt(b, v)
\* BEGIN AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_proof_ShowsSafety_T.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_PaxosHowToWinATuringAward/Voting_proof_ShowsSafety_T.tla
====
