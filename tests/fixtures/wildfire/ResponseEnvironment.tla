---- MODULE ResponseEnvironment ----
EXTENDS Wildfire
CONSTANTS MemorySentinel, UnlockedSentinel, InvalidSentinel, AcceptResponses

Home(x) == "ls"
InitialMemoryValue == [a \in Adr |-> [b \in 0..(DataLen-1) |-> 0]]

Issue(old, new, p, r) ==
    /\ old = 0
    /\ new = 1
    /\ r = [type |-> "Rd", adr |-> "a"]

Respond(old, new, p, r) ==
    /\ AcceptResponses
    /\ new = old + 1

AuditSpec == Spec /\ aInt = 0
Completion == (aInt = 1) ~> (aInt = 2)
AuditResponses == [type : {"Rd", "LL"}, adr : Adr, data : Data]
                  \cup [type : {"Wr", "SC", "FailedSC"}, adr : Adr]
ResponseReceptive ==
    \A p \in Proc, r \in AuditResponses : ENABLED ResponseToEnv(aInt, aInt', p, r)
NotReceptive == ~ResponseReceptive
====
