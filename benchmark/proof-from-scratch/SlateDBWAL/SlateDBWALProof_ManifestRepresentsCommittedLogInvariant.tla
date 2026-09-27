---- MODULE SlateDBWALProof_ManifestRepresentsCommittedLogInvariant ----
EXTENDS SlateDBWALProof_ManifestRepresentsCommittedLogInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ManifestRepresentsCommittedLogInvariant == Spec => []ManifestRepresentsCommittedLog
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
