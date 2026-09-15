---- MODULE FindHighest ----
EXTENDS FindHighestDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeInvariantHolds == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_TypeInvariantHolds.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_TypeInvariantHolds.tla

THEOREM InductiveInvariantHolds == Spec => []InductiveInvariant
\* BEGIN AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_InductiveInvariantHolds.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_InductiveInvariantHolds.tla

THEOREM DoneIndexValueThm == Spec => []DoneIndexValue
\* BEGIN AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_DoneIndexValueThm.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_DoneIndexValueThm.tla

THEOREM IsCorrect == Spec => []Correctness
\* BEGIN AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_IsCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_LearnProofs/FindHighest_IsCorrect.tla
====
