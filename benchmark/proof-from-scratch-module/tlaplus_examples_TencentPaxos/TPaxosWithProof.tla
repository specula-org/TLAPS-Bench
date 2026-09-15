---- MODULE TPaxosWithProof ----
EXTENDS TPaxosWithProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariant == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_TencentPaxos/TPaxosWithProof_Invariant.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TencentPaxos/TPaxosWithProof_Invariant.tla

THEOREM Consistent == Spec => []Consistency
\* BEGIN AGENT PROOF tlaplus_examples_TencentPaxos/TPaxosWithProof_Consistent.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TencentPaxos/TPaxosWithProof_Consistent.tla
====
