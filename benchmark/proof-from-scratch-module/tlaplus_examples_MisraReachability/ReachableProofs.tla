---- MODULE ReachableProofs ----
EXTENDS ReachableProofsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => []((pc = "Done") => (marked = Reachable))
\* BEGIN AGENT PROOF tlaplus_examples_MisraReachability/ReachableProofs_line197.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_MisraReachability/ReachableProofs_line197.tla
====
