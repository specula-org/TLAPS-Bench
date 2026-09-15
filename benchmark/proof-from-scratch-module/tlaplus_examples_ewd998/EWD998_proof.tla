---- MODULE EWD998_proof ----
EXTENDS EWD998_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Refinement == Spec => TD!Spec
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/EWD998_proof_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/EWD998_proof_Refinement.tla

THEOREM TerminationDetectionInv == Spec => []TerminationDetection
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/EWD998_proof_TerminationDetectionInv.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/EWD998_proof_TerminationDetectionInv.tla
====
