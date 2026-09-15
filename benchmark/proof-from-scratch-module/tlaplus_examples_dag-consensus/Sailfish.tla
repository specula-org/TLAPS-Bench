---- MODULE Sailfish ----
EXTENDS SailfishDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOKCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_dag-consensus/Sailfish_TypeOKCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_dag-consensus/Sailfish_TypeOKCorrect.tla

THEOREM AgreementCorrect == Spec => []Agreement
\* BEGIN AGENT PROOF tlaplus_examples_dag-consensus/Sailfish_AgreementCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_dag-consensus/Sailfish_AgreementCorrect.tla

THEOREM LivenessCorrect == Spec => []Liveness
\* BEGIN AGENT PROOF tlaplus_examples_dag-consensus/Sailfish_LivenessCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_dag-consensus/Sailfish_LivenessCorrect.tla
====
