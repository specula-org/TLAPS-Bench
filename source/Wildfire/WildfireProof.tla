-------------------------- MODULE WildfireProof ---------------------------
EXTENDS Wildfire

AlphaModel == INSTANCE Alpha

\* The environment must not disable delivery of a legal memory response.
\* This is an interface condition; protocol progress still needs a proof.
ResponseReceptive ==
    \A p \in Proc, r \in Response :
        ENABLED ResponseToEnv(aInt, aInt', p, r)

THEOREM Refinement ==
    (Spec /\ []ResponseReceptive) => AlphaModel!Spec
PROOF OMITTED

=============================================================================
