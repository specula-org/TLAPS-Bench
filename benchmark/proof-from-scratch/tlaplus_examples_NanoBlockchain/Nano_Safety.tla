---- MODULE Nano_Safety ----
EXTENDS Nano_SafetyDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM Safety == Spec => TypeInvariant /\ SafetyInvariant
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
