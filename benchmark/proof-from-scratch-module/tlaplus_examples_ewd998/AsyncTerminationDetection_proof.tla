---- MODULE AsyncTerminationDetection_proof ----
EXTENDS AsyncTerminationDetection_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == Init /\ [][Next]_vars => []Safe
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/AsyncTerminationDetection_proof_Safety.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/AsyncTerminationDetection_proof_Safety.tla

THEOREM Stability == Init /\ [][Next]_vars => Quiescence
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/AsyncTerminationDetection_proof_Stability.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/AsyncTerminationDetection_proof_Stability.tla

THEOREM Liveness == Spec => Live
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/AsyncTerminationDetection_proof_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/AsyncTerminationDetection_proof_Liveness.tla
====
