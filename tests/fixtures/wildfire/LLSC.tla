------------------------------ MODULE LLSC ------------------------------

EXTENDS Wildfire

CONSTANTS InMemoryVal, UnlockedVal, InvalidDataVal

ZeroBits == [i \in 0..(DataLen - 1) |-> 0]
OneBits  == [i \in 0..(DataLen - 1) |-> 1]

VProg == [p \in Proc |->
           << [type |-> "LL", adr |-> "a"],
              [type |-> "LL", adr |-> "b"],
              [type |-> "SC", adr |-> "a",
               mask |-> OneBits, data |-> OneBits] >>]

VProcLS(p) == "ls0"
VAdrLS(a)  == "ls0"
VInitMem   == [a \in Adr |-> ZeroBits]

VRequestFromEnv(ai, aip, p, r) ==
  /\ Len(ai.reqs[p]) < Len(VProg[p])
  /\ r = VProg[p][Len(ai.reqs[p]) + 1]
  /\ aip = [ai EXCEPT !.reqs[p] = Append(@, r)]

VResponseToEnv(ai, aip, p, r) ==
  aip = [ai EXCEPT !.resps[p] = Append(@, r)]

VInit == /\ Init
         /\ aInt = [reqs  |-> [p \in Proc |-> << >>],
                    resps |-> [p \in Proc |-> << >>]]

VSpec == VInit /\ [][Next]_wVars

PairableSC(rs, k) ==
  \E j \in 1..(k - 1) :
    /\ rs[j].type = "LL"
    /\ rs[j].adr  = rs[k].adr
    /\ \A i \in (j + 1)..(k - 1) : rs[i].type \notin {"LL", "SC"}

No_LLSC_violation ==
  \A p \in Proc :
    Cardinality({s \in DOMAIN aInt.resps[p] : aInt.resps[p][s].type = "SC"})
      <= Cardinality({k \in DOMAIN aInt.reqs[p] :
                        /\ aInt.reqs[p][k].type = "SC"
                        /\ PairableSC(aInt.reqs[p], k)})

=============================================================================
