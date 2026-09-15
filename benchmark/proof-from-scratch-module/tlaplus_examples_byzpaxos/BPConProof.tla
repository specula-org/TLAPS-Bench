---- MODULE BPConProof ----
EXTENDS BPConProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Invariance == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/BPConProof_Invariance.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/BPConProof_Invariance.tla

THEOREM Spec => P!Spec
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/BPConProof_P_Spec.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/BPConProof_P_Spec.tla

THEOREM chosen \subseteq P!chosen
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/BPConProof_line2170.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/BPConProof_line2170.tla
====
