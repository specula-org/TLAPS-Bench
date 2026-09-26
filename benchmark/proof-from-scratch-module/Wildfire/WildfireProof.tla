---- MODULE WildfireProof ----
EXTENDS WildfireProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Refinement == TraceSpec => AlphaModel!Spec
\* BEGIN AGENT PROOF Wildfire/WildfireProof_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF Wildfire/WildfireProof_Refinement.tla
====
