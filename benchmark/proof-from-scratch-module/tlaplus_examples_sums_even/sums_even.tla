---- MODULE sums_even ----
EXTENDS sums_evenDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM \A x \in Nat : Even(x+x)
\* BEGIN AGENT PROOF tlaplus_examples_sums_even/sums_even_line10.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_sums_even/sums_even_line10.tla

THEOREM T1 == \A x \in Nat: Even(x+x)
\* BEGIN AGENT PROOF tlaplus_examples_sums_even/sums_even_T1.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_sums_even/sums_even_T1.tla
====
