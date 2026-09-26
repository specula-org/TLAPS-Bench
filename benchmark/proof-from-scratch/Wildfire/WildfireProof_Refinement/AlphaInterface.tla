
-------------------------- MODULE AlphaInterface ----------------------------

EXTENDS Naturals, FiniteSets

VARIABLE aInt

CONSTANTS
  RequestFromEnv(_, _, _, _),
  ResponseToEnv(_, _, _, _),
  Proc,

  Adr,

  DataLen

ASSUME InterfaceParameters ==

  /\ IsFiniteSet(Proc)

  /\ (DataLen \in Nat) /\ (DataLen > 0)

Data == [0..(DataLen - 1) -> {0,1}]

-----------------------------------------------------------------------------

Request ==

       [type : {"MB"}]
  \cup [type : {"Rd", "LL"}, adr : Adr]
  \cup [type : {"Wr", "SC"}, adr : Adr, mask : Data, data : Data]

Response ==

       [type : {"Rd", "LL"}, adr : Adr, data : Data]
  \cup [type : {"Wr", "SC", "FailedSC"},  adr : Adr]
=============================================================================
