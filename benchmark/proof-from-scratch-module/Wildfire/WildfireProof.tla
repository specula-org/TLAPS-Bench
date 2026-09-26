---- MODULE WildfireProof ----
EXTENDS WildfireProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Refinement ==
    (Spec /\ []ResponseReceptive) => AlphaModel!Spec
\* BEGIN AGENT PROOF Wildfire/WildfireProof_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF Wildfire/WildfireProof_Refinement.tla
====
