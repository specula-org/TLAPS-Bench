---- MODULE SimpleRegular ----
EXTENDS SimpleRegularDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Correctness == Spec => []PCorrect
\* BEGIN AGENT PROOF tlaplus_examples_TeachingConcurrency/SimpleRegular_Correctness.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TeachingConcurrency/SimpleRegular_Correctness.tla

THEOREM Correctness2 == Spec => []PCorrect
\* BEGIN AGENT PROOF tlaplus_examples_TeachingConcurrency/SimpleRegular_Correctness2.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TeachingConcurrency/SimpleRegular_Correctness2.tla
====
