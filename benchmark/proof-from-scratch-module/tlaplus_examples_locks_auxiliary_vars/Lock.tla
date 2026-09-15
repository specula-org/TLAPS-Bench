---- MODULE Lock ----
EXTENDS LockDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM MutualExclusion == Spec => []LockInv
\* BEGIN AGENT PROOF tlaplus_examples_locks_auxiliary_vars/Lock_MutualExclusion.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_locks_auxiliary_vars/Lock_MutualExclusion.tla
====
