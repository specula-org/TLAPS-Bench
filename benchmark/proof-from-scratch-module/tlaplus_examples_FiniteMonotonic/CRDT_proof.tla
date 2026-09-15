---- MODULE CRDT_proof ----
EXTENDS CRDT_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => Monotonicity
\* BEGIN AGENT PROOF tlaplus_examples_FiniteMonotonic/CRDT_proof_Monotonicity.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FiniteMonotonic/CRDT_proof_Monotonicity.tla

THEOREM OGLiveness == OGSpec => <>(\A n, o \in Node : counter[n] = counter[o])
\* BEGIN AGENT PROOF tlaplus_examples_FiniteMonotonic/CRDT_proof_OGLiveness.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FiniteMonotonic/CRDT_proof_OGLiveness.tla

THEOREM FairSpec => Convergence
\* BEGIN AGENT PROOF tlaplus_examples_FiniteMonotonic/CRDT_proof_Convergence.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FiniteMonotonic/CRDT_proof_Convergence.tla
====
