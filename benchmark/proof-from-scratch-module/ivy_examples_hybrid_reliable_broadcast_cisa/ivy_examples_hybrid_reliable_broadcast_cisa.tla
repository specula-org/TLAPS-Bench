---- MODULE ivy_examples_hybrid_reliable_broadcast_cisa ----
EXTENDS ivy_examples_hybrid_reliable_broadcast_cisaDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == SafetySpec => []Unforgeability
\* BEGIN AGENT PROOF ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa_Safety.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa_Safety.tla

THEOREM CorrectnessLiveness == Spec => Correctness
\* BEGIN AGENT PROOF ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa_CorrectnessLiveness.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa_CorrectnessLiveness.tla

THEOREM RelayLiveness == Spec => Relay
\* BEGIN AGENT PROOF ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa_RelayLiveness.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa_RelayLiveness.tla
====
