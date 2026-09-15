---- MODULE tcp_proof ----
EXTENDS tcp_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_tcp/tcp_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_tcp/tcp_proof_TypeCorrect.tla

THEOREM InvInit == Init => Inv
\* BEGIN AGENT PROOF tlaplus_examples_tcp/tcp_proof_InvInit.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_tcp/tcp_proof_InvInit.tla

THEOREM SpecImpliesInv == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_tcp/tcp_proof_SpecImpliesInv.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_tcp/tcp_proof_SpecImpliesInv.tla
====
