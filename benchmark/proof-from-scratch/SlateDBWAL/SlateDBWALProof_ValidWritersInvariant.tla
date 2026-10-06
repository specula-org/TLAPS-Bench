---- MODULE SlateDBWALProof_ValidWritersInvariant ----
EXTENDS SlateDBWALProof_ValidWritersInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ValidWritersInvariant == Spec => []ValidWriters
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
