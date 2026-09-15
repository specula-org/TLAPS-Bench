----------------------------- MODULE Sailfish_AgreementCorrectDefs -----------------------------

EXTENDS SailfishModel

INSTANCE BlockDag 

Agreement == \A n1,n2 \in N \ F : Compatible(log[n1], log[n2])

===========================================================================
