---- MODULE WalgitProof_ValidLogSegmentsInvariant ----
EXTENDS WalgitProof_ValidLogSegmentsInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ValidLogSegmentsInvariant == Spec => []ValidLogSegments
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
