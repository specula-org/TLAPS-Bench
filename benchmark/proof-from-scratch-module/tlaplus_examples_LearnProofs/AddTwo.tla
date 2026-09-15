---- MODULE AddTwo ----
EXTENDS AddTwoDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeInvariant == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_LearnProofs/AddTwo_TypeInvariant.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_LearnProofs/AddTwo_TypeInvariant.tla

THEOREM Spec => []Even
\* BEGIN AGENT PROOF tlaplus_examples_LearnProofs/AddTwo_Even.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_LearnProofs/AddTwo_Even.tla
====
