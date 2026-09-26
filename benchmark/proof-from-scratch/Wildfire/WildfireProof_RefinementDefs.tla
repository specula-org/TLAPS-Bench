-------------------------- MODULE WildfireProof_RefinementDefs ---------------------------
EXTENDS Wildfire

AlphaModel == INSTANCE Alpha

ResponseReceptive ==
    \A p \in Proc, r \in Response :
        ENABLED ResponseToEnv(aInt, aInt', p, r)

=============================================================================
