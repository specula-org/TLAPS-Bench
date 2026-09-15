---- MODULE ivy_examples_ticket ----
EXTENDS ivy_examples_ticketDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == SafetySpec => []MutualExclusion
\* BEGIN AGENT PROOF ivy_examples_ticket/ivy_examples_ticket_Safety.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_ticket/ivy_examples_ticket_Safety.tla

THEOREM Liveness == Spec => NonStarvation
\* BEGIN AGENT PROOF ivy_examples_ticket/ivy_examples_ticket_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_ticket/ivy_examples_ticket_Liveness.tla
====
