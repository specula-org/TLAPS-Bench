---- MODULE ivy_examples_ticket_nested ----
EXTENDS ivy_examples_ticket_nestedDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == SafetySpec => []MutualExclusion
\* BEGIN AGENT PROOF ivy_examples_ticket_nested/ivy_examples_ticket_nested_Safety.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_ticket_nested/ivy_examples_ticket_nested_Safety.tla

THEOREM Liveness == Spec => NonStarvation
\* BEGIN AGENT PROOF ivy_examples_ticket_nested/ivy_examples_ticket_nested_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_ticket_nested/ivy_examples_ticket_nested_Liveness.tla
====
