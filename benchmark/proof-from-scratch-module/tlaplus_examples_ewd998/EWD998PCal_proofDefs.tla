---------------------------- MODULE EWD998PCal_proofDefs ----------------------------

EXTENDS EWD998PCal, TLAPS

ColorSet == {"white", "black"}
PMsg == [type: {"pl"}]
TMsg == [type: {"tok"}, q: Int, color: ColorSet]
Msg  == PMsg \cup TMsg

BagOf(S) == UNION { [T -> Nat \ {0}] : T \in SUBSET S }

NetworkOK ==
  /\ network \in [Node -> BagOf(Msg)]
  /\ \E n \in Node : \E t \in DOMAIN network[n] :
       /\ t.type = "tok"
       /\ network[n][t] = 1
       /\ \A n2 \in Node : \A t2 \in DOMAIN network[n2] :
              t2.type = "tok" => (n2 = n /\ t2 = t)

PCalTypeOK ==
  /\ active \in [Node -> BOOLEAN]
  /\ color \in [Node -> ColorSet]
  /\ counter \in [Node -> Int]
  /\ NetworkOK

=============================================================================
