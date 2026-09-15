----------------------------- MODULE BakeryModel ---------------------------------

EXTENDS Naturals, TLAPS

CONSTANT N 
ASSUME N \in Nat

P == 1..N 

VARIABLES num, flag, pc

LL(j, i) == \/ num[j] < num[i]
            \/ /\ num[i] = num[j]
               /\ j =< i

VARIABLES unread, max, nxt

vars == << num, flag, pc, unread, max, nxt >>

ProcSet == (P)

Init == 
        /\ num = [i \in P |-> 0]
        /\ flag = [i \in P |-> FALSE]
        
        /\ unread \in [P -> SUBSET P]
        /\ max \in [P -> Nat]
        /\ nxt \in [P -> P]
        /\ pc = [self \in ProcSet |-> "p1"]

p1(self) == /\ pc[self] = "p1"
            /\ unread' = [unread EXCEPT ![self] = P \ {self}]
            /\ max' = [max EXCEPT ![self] = 0]
            /\ \E repeat \in BOOLEAN:
                 IF repeat
                    THEN /\ flag' = [flag EXCEPT ![self] = ~ flag[self]]
                         /\ pc' = [pc EXCEPT ![self] = "p1"]
                    ELSE /\ flag' = [flag EXCEPT ![self] = TRUE]
                         /\ pc' = [pc EXCEPT ![self] = "p2"]
            /\ UNCHANGED << num, nxt >>

p2(self) == /\ pc[self] = "p2"
            /\ IF unread[self] # {}
                  THEN /\ \E i \in unread[self]:
                            /\ unread' = [unread EXCEPT ![self] = unread[self] \ {i}]
                            /\ IF num[i] > max[self]
                                  THEN /\ max' = [max EXCEPT ![self] = num[i]]
                                  ELSE /\ TRUE
                                       /\ max' = max
                       /\ pc' = [pc EXCEPT ![self] = "p2"]
                  ELSE /\ pc' = [pc EXCEPT ![self] = "p3"]
                       /\ UNCHANGED << unread, max >>
            /\ UNCHANGED << num, flag, nxt >>

p3(self) == /\ pc[self] = "p3"
            /\ \E repeat \in BOOLEAN:
                 \E k \in Nat:
                   IF repeat
                      THEN /\ num' = [num EXCEPT ![self] = k]
                           /\ pc' = [pc EXCEPT ![self] = "p3"]
                      ELSE /\ \E i \in {j \in Nat : j > max[self]}:
                                num' = [num EXCEPT ![self] = i]
                           /\ pc' = [pc EXCEPT ![self] = "p4"]
            /\ UNCHANGED << flag, unread, max, nxt >>

p4(self) == /\ pc[self] = "p4"
            /\ unread' = [unread EXCEPT ![self] = P \ {self}]
            /\ \E repeat \in BOOLEAN:
                 IF repeat
                    THEN /\ flag' = [flag EXCEPT ![self] = ~ flag[self]]
                         /\ pc' = [pc EXCEPT ![self] = "p4"]
                    ELSE /\ flag' = [flag EXCEPT ![self] = FALSE]
                         /\ pc' = [pc EXCEPT ![self] = "p5"]
            /\ UNCHANGED << num, max, nxt >>

p5(self) == /\ pc[self] = "p5"
            /\ IF unread[self] # {}
                  THEN /\ \E i \in unread[self]:
                            nxt' = [nxt EXCEPT ![self] = i]
                       /\ ~ flag[nxt'[self]]
                       /\ pc' = [pc EXCEPT ![self] = "p6"]
                  ELSE /\ pc' = [pc EXCEPT ![self] = "cs"]
                       /\ nxt' = nxt
            /\ UNCHANGED << num, flag, unread, max >>

p6(self) == /\ pc[self] = "p6"
            /\ \/ num[nxt[self]] = 0
               \/ LL(self, nxt[self])
            /\ unread' = [unread EXCEPT ![self] = unread[self] \ {nxt[self]}]
            /\ pc' = [pc EXCEPT ![self] = "p5"]
            /\ UNCHANGED << num, flag, max, nxt >>

cs(self) == /\ pc[self] = "cs"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "p7"]
            /\ UNCHANGED << num, flag, unread, max, nxt >>

p7(self) == /\ pc[self] = "p7"
            /\ \E repeat \in BOOLEAN:
                 \E k \in Nat:
                   IF repeat
                      THEN /\ num' = [num EXCEPT ![self] = k]
                           /\ pc' = [pc EXCEPT ![self] = "p7"]
                      ELSE /\ num' = [num EXCEPT ![self] = 0]
                           /\ pc' = [pc EXCEPT ![self] = "p1"]
            /\ UNCHANGED << flag, unread, max, nxt >>

p(self) == p1(self) \/ p2(self) \/ p3(self) \/ p4(self) \/ p5(self)
              \/ p6(self) \/ cs(self) \/ p7(self)

Next == (\E self \in P: p(self))

Spec == Init /\ [][Next]_vars

=============================================================================
