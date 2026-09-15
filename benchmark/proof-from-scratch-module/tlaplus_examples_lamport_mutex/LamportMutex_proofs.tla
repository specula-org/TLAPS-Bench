---- MODULE LamportMutex_proofs ----
EXTENDS LamportMutex_proofsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == Spec => []Mutex
\* BEGIN AGENT PROOF tlaplus_examples_lamport_mutex/LamportMutex_proofs_Safety.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_lamport_mutex/LamportMutex_proofs_Safety.tla

THEOREM BoundedNetworkInv == Spec => []BoundedNetwork
\* BEGIN AGENT PROOF tlaplus_examples_lamport_mutex/LamportMutex_proofs_BoundedNetworkInv.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_lamport_mutex/LamportMutex_proofs_BoundedNetworkInv.tla
====
