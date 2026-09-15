---- MODULE Simple ----
EXTENDS SimpleDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Correctness == Spec => []PCorrect
\* BEGIN AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_Correctness.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_Correctness.tla

THEOREM Correctness2 == Spec => []PCorrect
\* BEGIN AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_Correctness2.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_Correctness2.tla
====
