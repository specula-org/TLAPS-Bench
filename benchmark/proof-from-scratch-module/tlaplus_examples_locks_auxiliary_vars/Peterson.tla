---- MODULE Peterson ----
EXTENDS PetersonDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM IndInvariant == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_locks_auxiliary_vars/Peterson_IndInvariant.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_locks_auxiliary_vars/Peterson_IndInvariant.tla

THEOREM Refinement == Spec => L!Spec
\* BEGIN AGENT PROOF tlaplus_examples_locks_auxiliary_vars/Peterson_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_locks_auxiliary_vars/Peterson_Refinement.tla
====
