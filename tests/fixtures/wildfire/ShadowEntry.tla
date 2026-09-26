------------------------------ MODULE ShadowEntry -----------------------------

EXTENDS Wildfire

CONSTANTS InMemoryVal, UnlockedVal, InvalidDataVal

ZeroBits == [i \in 0..(DataLen - 1) |-> 0]
OneBits  == [i \in 0..(DataLen - 1) |-> 1]

RdReq(ad) == [type |-> "Rd", adr |-> ad]
WrReq(ad) == [type |-> "Wr", adr |-> ad, mask |-> OneBits, data |-> OneBits]
MBReq     == [type |-> "MB"]

VProg == [p \in Proc |->
  CASE p = "p0" -> << RdReq("a"), WrReq("a") >>
    [] p = "p1" -> << RdReq("a"), MBReq, WrReq("b") >>
    [] OTHER    -> << RdReq("a"), RdReq("b"), MBReq, RdReq("a") >> ]

VProcLS(p) == IF p = "q" THEN "ls1" ELSE "ls0"
VAdrLS(ad) == IF ad = "a" THEN "ls0" ELSE "ls1"
VInitMem   == [ad \in Adr |-> ZeroBits]

StageOK(ai, p) ==
  LET np == Len(ai.reqs[p]) IN
  CASE p = "p0" ->
         CASE np = 0 -> TRUE
           [] np = 1 -> Len(ai.resps["q"]) >= 1
           [] OTHER  -> FALSE
    [] p = "p1" ->
         CASE np = 0 -> Len(ai.resps["p0"]) >= 2
           [] np = 1 -> TRUE
           [] np = 2 -> TRUE
           [] OTHER  -> FALSE
    [] OTHER ->
         CASE np = 0 -> TRUE
           [] np = 1 -> Len(ai.resps["p1"]) >= 2
           [] np = 2 -> TRUE
           [] np = 3 -> TRUE
           [] OTHER  -> FALSE

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

InvalA == [type |-> "Inval", cmdr |-> "p0", dest |-> "q", adr |-> "a"]

Prune ==
  /\ (Len(aInt.resps["q"]) >= 1 /\ Len(aInt.resps["q"]) < 3)
       => cache["q"]["a"].state = "SharedClean"
  /\ (Len(aInt.resps["p0"]) >= 2 /\ Len(aInt.resps["q"]) < 3)
       => InvalA \in msgsInQueue(Q.GSToLS["ls1"])

VNext == Next /\ Prune'

VSpec == VInit /\ Prune /\ [][VNext]_wVars

shadow_entry_violation ==
  /\ Len(aInt.resps["p1"]) >= 1
  /\ aInt.resps["p1"][1] = [type |-> "Rd", adr |-> "a", data |-> OneBits]
  /\ Len(aInt.resps["q"]) = 3
  /\ aInt.resps["q"][1] = [type |-> "Rd", adr |-> "a", data |-> ZeroBits]
  /\ aInt.resps["q"][2] = [type |-> "Rd", adr |-> "b", data |-> OneBits]
  /\ aInt.resps["q"][3] = [type |-> "Rd", adr |-> "a", data |-> ZeroBits]

No_shadow_entry_violation == ~shadow_entry_violation
=============================================================================
