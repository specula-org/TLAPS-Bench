---- MODULE ParReachProofs ----
EXTENDS ParReachProofsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => R!Init /\ [][R!Next]_R!vars
\* BEGIN AGENT PROOF tlaplus_examples_MisraReachability/ParReachProofs_line18.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_MisraReachability/ParReachProofs_line18.tla
====
