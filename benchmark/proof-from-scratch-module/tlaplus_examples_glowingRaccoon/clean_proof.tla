---- MODULE clean_proof ----
EXTENDS clean_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM PrimerPositive == Spec => []primerPositive
\* BEGIN AGENT PROOF tlaplus_examples_glowingRaccoon/clean_proof_PrimerPositive.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_glowingRaccoon/clean_proof_PrimerPositive.tla

THEOREM Preservation == Spec => []preservationInvariant
\* BEGIN AGENT PROOF tlaplus_examples_glowingRaccoon/clean_proof_Preservation.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_glowingRaccoon/clean_proof_Preservation.tla
====
