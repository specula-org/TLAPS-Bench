---- MODULE WalgitProof_ValidReplicasInvariant ----
EXTENDS WalgitProof_ValidReplicasInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ValidReplicasInvariant == Spec => []ValidReplicas
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
