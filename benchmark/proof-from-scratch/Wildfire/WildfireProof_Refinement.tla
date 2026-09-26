---- MODULE WildfireProof_Refinement ----
EXTENDS WildfireProof_RefinementDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM Refinement == Spec => AlphaModel!Spec
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
