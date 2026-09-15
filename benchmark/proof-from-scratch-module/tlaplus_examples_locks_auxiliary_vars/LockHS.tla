---- MODULE LockHS ----
EXTENDS LockHSDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM StutterConstantCondition(1..2, 1, LAMBDA j : j-1)
\* BEGIN AGENT PROOF tlaplus_examples_locks_auxiliary_vars/LockHS_line31.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_locks_auxiliary_vars/LockHS_line31.tla

THEOREM SpecHS => P!Spec
\* BEGIN AGENT PROOF tlaplus_examples_locks_auxiliary_vars/LockHS_P_Spec.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_locks_auxiliary_vars/LockHS_P_Spec.tla
====
