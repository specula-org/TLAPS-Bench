---- MODULE CigaretteSmokers_proof ----
EXTENDS CigaretteSmokers_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_CigaretteSmokers/CigaretteSmokers_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_CigaretteSmokers/CigaretteSmokers_proof_TypeCorrect.tla

THEOREM AtMostOneCorrect == Spec => []AtMostOne
\* BEGIN AGENT PROOF tlaplus_examples_CigaretteSmokers/CigaretteSmokers_proof_AtMostOneCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_CigaretteSmokers/CigaretteSmokers_proof_AtMostOneCorrect.tla
====
