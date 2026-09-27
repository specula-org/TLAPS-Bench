---- MODULE WalgitProof_ReplicaStateIsCommittedPrefixInvariant ----
EXTENDS WalgitProof_ReplicaStateIsCommittedPrefixInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ReplicaStateIsCommittedPrefixInvariant == Spec => []ReplicaStateIsCommittedPrefix
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
