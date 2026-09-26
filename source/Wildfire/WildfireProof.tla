-------------------------- MODULE WildfireProof ---------------------------
EXTENDS Wildfire

AlphaModel == INSTANCE Alpha

THEOREM Refinement == Spec => AlphaModel!Spec
PROOF OMITTED

=============================================================================
