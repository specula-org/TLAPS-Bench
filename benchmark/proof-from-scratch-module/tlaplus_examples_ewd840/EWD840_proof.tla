---- MODULE EWD840_proof ----
EXTENDS EWD840_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == Spec => []TerminationDetection
\* BEGIN AGENT PROOF tlaplus_examples_ewd840/EWD840_proof_Safety.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd840/EWD840_proof_Safety.tla

THEOREM Spec => TD!Spec
\* BEGIN AGENT PROOF tlaplus_examples_ewd840/EWD840_proof_TD_Spec.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd840/EWD840_proof_TD_Spec.tla
====
