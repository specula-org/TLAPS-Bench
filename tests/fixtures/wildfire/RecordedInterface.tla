---- MODULE RecordedInterface ----
EXTENDS WildfireProofDefs
CONSTANTS MemorySentinel, UnlockedSentinel, InvalidSentinel,
          RemoteMemory, MixedProgram

ProcessorHome(p) == IF RemoteMemory THEN "cpu" ELSE "mem"
AddressHome(a) == "mem"
InitialMemoryValue == [a \in Adr |-> [b \in 0..(DataLen-1) |-> 0]]
OneBits == [b \in 0..(DataLen-1) |-> 1]
AuditResponses == [type : {"Rd", "LL"}, adr : Adr, data : Data]
                  \cup [type : {"Wr", "SC", "FailedSC"}, adr : Adr]

\* These inherited parameters must not control either recorded instance.
UnusedInterface(old, new, p, r) == FALSE

Program == IF MixedProgram
           THEN <<[type |-> "LL", adr |-> "a"],
                  [type |-> "SC", adr |-> "a", mask |-> OneBits, data |-> OneBits],
                  [type |-> "MB"], [type |-> "Rd", adr |-> "a"]>>
           ELSE <<[type |-> "Rd", adr |-> "a"]>>

Issued == Cardinality({i \in DOMAIN aInt : aInt[i].kind = "request"})
Responded == Cardinality({i \in DOMAIN aInt : aInt[i].kind = "response"})
ExpectedResponses == IF MixedProgram THEN 3 ELSE 1

IssueNext == /\ Issued < Len(Program)
             /\ Protocol!ProcReceiveRequest("p", Program[Issued+1])
NoNewRequest == IF Len(aInt') = Len(aInt)
               THEN TRUE ELSE aInt'[Len(aInt')].kind = "response"

\* Restrict client requests only; keep concrete processing and fairness.
AuditNext == IssueNext \/ (Protocol!Next /\ NoNewRequest)
AuditSpec == /\ Protocol!Init /\ aInt = <<>>
             /\ [][AuditNext]_wVars /\ Protocol!Liveness

Completion == (Issued = Len(Program)) ~> (Responded = ExpectedResponses)
NeverCompletes == Responded < ExpectedResponses
Receptive == \A p \in Proc, r \in AuditResponses : ENABLED RecordResponse(aInt, aInt', p, r)
ValidHistory == \A i \in DOMAIN aInt :
    /\ aInt[i].proc \in Proc
    /\ IF aInt[i].kind = "request"
       THEN aInt[i].value \in Request
       ELSE aInt[i].kind = "response" /\ aInt[i].value \in AuditResponses
====
