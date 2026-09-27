---- MODULE WalgitProof_ValidManifestInvariant ----
EXTENDS WalgitProof_ValidManifestInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ValidManifestInvariant == Spec => []ValidManifest
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
