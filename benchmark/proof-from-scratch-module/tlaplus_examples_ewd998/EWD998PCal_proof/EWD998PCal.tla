------------------------------- MODULE EWD998PCal -------------------------------

EXTENDS Integers, Bags, BagsExt

CONSTANT N
ASSUME NAssumption == N \in Nat \ {0} 

Node == 0 .. N-1

Initiator == 0 

VARIABLE network

passMsg(net, from, oldMsg, to, newMsg) == [ net EXCEPT ![from] = BagRemove(@, oldMsg), ![to] = BagAdd(@, newMsg) ]
sendMsg(net, to, msg) == [ net EXCEPT ![to] = BagAdd(@, msg) ]
dropMsg(net, to, msg) == [ net EXCEPT ![to] = BagRemove(@, msg) ]
pendingMsgs(net, rcv) == DOMAIN net[rcv]

VARIABLES active, color, counter

vars == << network, active, color, counter >>

Init == 
        /\ network = [n \in Node |-> IF n = Initiator THEN SetToBag({[type|-> "tok", q |-> 0, color |-> "black"]}) ELSE EmptyBag]
        
        /\ active \in [Node -> BOOLEAN]
        /\ color = [self \in Node |-> "black"]
        /\ counter = [self \in Node |-> 0]

node(self) == \/ /\ active[self]
                 /\ \E to \in Node \ {self}:
                      network' = sendMsg(network, to, [type|-> "pl"])
                 /\ counter' = [counter EXCEPT ![self] = counter[self] + 1]
                 /\ UNCHANGED <<active, color>>
              \/ /\ \E msg \in pendingMsgs(network, self):
                      /\ msg.type = "pl"
                      /\ counter' = [counter EXCEPT ![self] = counter[self] - 1]
                      /\ active' = [active EXCEPT ![self] = TRUE]
                      /\ color' = [color EXCEPT ![self] = "black"]
                      /\ network' = dropMsg(network, self, msg)
              \/ /\ active' = [active EXCEPT ![self] = FALSE]
                 /\ UNCHANGED <<network, color, counter>>
              \/ /\ self # Initiator
                 /\ \E tok \in pendingMsgs(network, self):
                      /\ tok.type = "tok" /\ ~active[self]
                      /\ network' = passMsg(network, self, tok, self-1, [type|-> "tok", q |-> tok.q + counter[self], color |-> (IF color[self] = "black" THEN "black" ELSE tok.color)])
                      /\ color' = [color EXCEPT ![self] = "white"]
                 /\ UNCHANGED <<active, counter>>
              \/ /\ self = Initiator
                 /\ \E tok \in pendingMsgs(network, self):
                      /\ tok.type = "tok" /\ (color[self] = "black" \/ tok.q + counter[self] # 0 \/ tok.color = "black")
                      /\ network' = passMsg(network, self, tok, N-1, [type|-> "tok", q |-> 0, color |-> "white"])
                      /\ color' = [color EXCEPT ![self] = "white"]
                 /\ UNCHANGED <<active, counter>>

Next == (\E self \in Node: node(self))

Spec == /\ Init /\ [][Next]_vars
        /\ \A self \in Node : WF_vars(node(self))

-----------------------------------------------------------------------------

token ==
    LET tpos == CHOOSE i \in Node : \E m \in DOMAIN network[i]: m.type = "tok"
        tok == CHOOSE m \in DOMAIN network[tpos] : m.type = "tok"
    IN [pos |-> tpos, q |-> tok.q, color |-> tok.color]

pending ==
    [n \in Node |-> IF [type|->"pl"] \in DOMAIN network[n] THEN network[n][[type|->"pl"]] ELSE 0]

EWD998 == INSTANCE EWD998

-----------------------------------------------------------------------------

=============================================================================
