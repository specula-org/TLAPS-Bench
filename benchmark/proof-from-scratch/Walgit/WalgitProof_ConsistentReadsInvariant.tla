---- MODULE WalgitProof_ConsistentReadsInvariant ----
EXTENDS WalgitProof_ConsistentReadsInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ConsistentReadsInvariant == Spec => []ConsistentReads
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
