---- MODULE SyncTerminationDetection_proof ----
EXTENDS SyncTerminationDetection_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM CorrectDetection == Spec => TDCorrect
\* BEGIN AGENT PROOF tlaplus_examples_ewd840/SyncTerminationDetection_proof_CorrectDetection.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd840/SyncTerminationDetection_proof_CorrectDetection.tla

THEOREM Quiescent == Spec => Quiescence
\* BEGIN AGENT PROOF tlaplus_examples_ewd840/SyncTerminationDetection_proof_Quiescent.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd840/SyncTerminationDetection_proof_Quiescent.tla

THEOREM Live == Spec => Liveness
\* BEGIN AGENT PROOF tlaplus_examples_ewd840/SyncTerminationDetection_proof_Live.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd840/SyncTerminationDetection_proof_Live.tla
====
