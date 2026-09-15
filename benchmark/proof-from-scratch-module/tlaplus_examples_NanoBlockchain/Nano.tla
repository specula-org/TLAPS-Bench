---- MODULE Nano ----
EXTENDS NanoDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == Spec => TypeInvariant /\ SafetyInvariant
\* BEGIN AGENT PROOF tlaplus_examples_NanoBlockchain/Nano_Safety.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_NanoBlockchain/Nano_Safety.tla
====
