------------------------------ MODULE Alpha ---------------------------------

EXTENDS AlphaInterface

Inner(InitMem, reqSeq, beforeOrder) == INSTANCE InnerAlpha

Spec ==

  \E InitMem \in [Adr -> Data] :
    \EE reqSeq, beforeOrder : Inner(InitMem, reqSeq, beforeOrder)!InnerSpec
=============================================================================
