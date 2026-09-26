------------------------------ MODULE ProbeOrder -----------------------------

EXTENDS Wildfire

CONSTANTS InMemoryVal, UnlockedVal, InvalidDataVal

ZeroBits == [i \in 0..(DataLen - 1) |-> 0]
OneBits  == [i \in 0..(DataLen - 1) |-> 1]

RdReq(a) == [type |-> "Rd", adr |-> a]
WrReq(a) == [type |-> "Wr", adr |-> a, mask |-> OneBits, data |-> OneBits]
MBReq    == [type |-> "MB"]

VProg == [p \in Proc |->
  IF p = "p0" THEN << RdReq("x"), WrReq("x"), MBReq, WrReq("y") >>
              ELSE << RdReq("x"), RdReq("y"), MBReq, RdReq("x") >>]

VProcLS(p) == IF p = "p0" THEN "ls0" ELSE "ls1"
VAdrLS(a)  == IF a = "x" THEN "ls0" ELSE "ls1"
VInitMem   == [a \in Adr |-> ZeroBits]

StageOK(ai, p) ==
  LET np == Len(ai.reqs[p]) IN
  IF p = "p0"
  THEN CASE np = 0 -> TRUE
       []   np = 1 -> Len(ai.resps["p1"]) >= 1
       []   np = 2 -> Len(ai.resps["p0"]) >= 2
       []   np = 3 -> TRUE
       []   OTHER  -> FALSE
  ELSE CASE np = 0 -> TRUE
       []   np = 1 -> Len(ai.reqs["p0"]) >= 4
       []   np = 2 -> TRUE
       []   np = 3 -> TRUE
       []   OTHER  -> FALSE

VRequestFromEnv(ai, aip, p, r) ==
  /\ Len(ai.reqs[p]) < Len(VProg[p])
  /\ r = VProg[p][Len(ai.reqs[p]) + 1]
  /\ StageOK(ai, p)
  /\ aip = [ai EXCEPT !.reqs[p] = Append(@, r)]

VResponseToEnv(ai, aip, p, r) ==
  aip = [ai EXCEPT !.resps[p] = Append(@, r)]

VInit == /\ Init
         /\ aInt = [reqs  |-> [p \in Proc |-> << >>],
                    resps |-> [p \in Proc |-> << >>]]

InvalX == [type |-> "Inval", cmdr |-> "p0", dest |-> "p1", adr |-> "x"]

Prune ==
  /\ (Len(aInt.resps["p1"]) >= 1 /\ Len(aInt.resps["p1"]) < 3)
       => cache["p1"]["x"].state = "SharedClean"
  /\ (Len(aInt.reqs["p1"]) >= 2 /\ Len(aInt.resps["p1"]) < 3)
       => InvalX \in msgsInQueue(Q.GSToLS["ls1"])

VNext == Next /\ Prune'

VSpec == VInit /\ Prune /\ [][VNext]_wVars

probe_ordering_violation ==
  /\ Len(aInt.resps["p1"]) = 3
  /\ aInt.resps["p1"][1] = [type |-> "Rd", adr |-> "x", data |-> ZeroBits]
  /\ aInt.resps["p1"][2] = [type |-> "Rd", adr |-> "y", data |-> OneBits]
  /\ aInt.resps["p1"][3] = [type |-> "Rd", adr |-> "x", data |-> ZeroBits]

No_probe_ordering_violation == ~probe_ordering_violation

=============================================================================
