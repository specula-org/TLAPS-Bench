---- MODULE ivy_examples_tlb ----
EXTENDS ivy_examples_tlbDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == SafetySpec => []NoError
\* BEGIN AGENT PROOF ivy_examples_tlb/ivy_examples_tlb_Safety.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_tlb/ivy_examples_tlb_Safety.tla

THEOREM Liveness == Spec => NonStarvation
\* BEGIN AGENT PROOF ivy_examples_tlb/ivy_examples_tlb_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_tlb/ivy_examples_tlb_Liveness.tla
====
