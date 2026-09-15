---- MODULE PaxosProof ----
EXTENDS PaxosProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => []StructOK1
\* BEGIN AGENT PROOF Consensus/PaxosProof_StructOK1.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/PaxosProof_StructOK1.tla

THEOREM \A b \in Ballot, v \in Value : 
            Phase2a(b,v) /\ Inv => \E Q \in Quorum : V!ShowsSafeAt(Q,b,v)
\* BEGIN AGENT PROOF Consensus/PaxosProof_line91.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/PaxosProof_line91.tla

THEOREM Next /\ Inv => V!Next \/ UNCHANGED <<votes,maxBal>>
\* BEGIN AGENT PROOF Consensus/PaxosProof_line130.tla
PROOF OMITTED
\* END AGENT PROOF Consensus/PaxosProof_line130.tla
====
