---- MODULE Peterson ----
EXTENDS PetersonDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => []MutualExclusion
\* BEGIN AGENT PROOF Peterson/Peterson_MutualExclusion.tla
PROOF OMITTED
\* END AGENT PROOF Peterson/Peterson_MutualExclusion.tla

THEOREM FairSpec => Liveness
\* BEGIN AGENT PROOF Peterson/Peterson_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF Peterson/Peterson_Liveness.tla
====
