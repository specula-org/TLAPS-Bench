---------------- MODULE ivy_examples_hybrid_reliable_broadcast_cisaModel ----------------
EXTENDS TLAPS, FiniteSets

CONSTANTS
  Node, QuorumA, QuorumB,
  MemberA, MemberB,
  FaultA, FaultC, FaultS, FaultI,
  RcvInit

ASSUME TypeAssumption ==
  /\ Node # {}
  /\ QuorumA # {}
  /\ QuorumB # {}
  /\ MemberA \in [Node -> [QuorumA -> BOOLEAN]]
  /\ MemberB \in [Node -> [QuorumB -> BOOLEAN]]
  /\ FaultA \subseteq Node
  /\ FaultC \subseteq Node
  /\ FaultS \subseteq Node
  /\ FaultI \subseteq Node
  /\ RcvInit \subseteq Node

ASSUME NodeFinite == IsFiniteSet(Node)

InA(n, q) == MemberA[n][q]
InB(n, q) == MemberB[n][q]

Obedient(n) ==
  /\ n \notin FaultS
  /\ n \notin FaultA

Symmetric(n) ==
  /\ n \notin FaultI
  /\ n \notin FaultA

Correct(n) ==
  /\ n \notin FaultC
  /\ n \notin FaultI
  /\ n \notin FaultS
  /\ n \notin FaultA

ASSUME QuorumAssumption ==
  /\ \E b \in QuorumB :
       \A n \in Node :
         InB(n, b) => Correct(n)
  /\ \A a \in QuorumA :
       \E n \in Node :
         /\ InA(n, a)
         /\ Obedient(n)
  /\ \A b \in QuorumB :
       \E a \in QuorumA :
         \A n \in Node :
           InA(n, a) =>
             /\ InB(n, b)
             /\ Symmetric(n)
  /\ \A n \in Node : ~(n \in FaultC /\ n \in FaultI)
  /\ \A n \in Node : ~(n \in FaultC /\ n \in FaultS)
  /\ \A n \in Node : ~(n \in FaultC /\ n \in FaultA)
  /\ \A n \in Node : ~(n \in FaultI /\ n \in FaultS)
  /\ \A n \in Node : ~(n \in FaultI /\ n \in FaultA)
  /\ \A n \in Node : ~(n \in FaultS /\ n \in FaultA)

VARIABLES accept, sentMsg, rcvMsg

vars == << accept, sentMsg, rcvMsg >>

HasAQuorumRcv(n, rm) ==
  \E a \in QuorumA :
    \A src \in Node : InA(src, a) => rm[src][n]

HasBQuorumRcv(n, rm) ==
  \E b \in QuorumB :
    \A src \in Node : InB(src, b) => rm[src][n]

SendAllFrom(sm, n) ==
  [src \in Node |->
    IF src = n THEN [dst \in Node |-> TRUE] ELSE sm[src]]

SetReceiveColumn(rm, n, col) ==
  [src \in Node |->
    [dst \in Node |->
      IF dst = n THEN col[src] ELSE rm[src][dst]]]

Init ==
  /\ accept = [n \in Node |-> FALSE]
  /\ sentMsg = [src \in Node |-> [dst \in Node |-> FALSE]]
  /\ rcvMsg = [src \in Node |-> [dst \in Node |-> FALSE]]

ReceiveInit(n) ==
  /\ n \in Node
  /\ n \in RcvInit
  /\ sentMsg' = SendAllFrom(sentMsg, n)
  /\ UNCHANGED << accept, rcvMsg >>

ReceiveMsg(n, s) ==
  /\ n \in Node
  /\ s \in Node
  /\ sentMsg[s][n]
  /\ LET newRcv == [rcvMsg EXCEPT ![s][n] = TRUE] IN
       /\ rcvMsg' = newRcv
       /\ accept' =
            IF HasBQuorumRcv(n, newRcv)
              THEN [accept EXCEPT ![n] = TRUE]
              ELSE accept
       /\ sentMsg' =
            IF HasAQuorumRcv(n, newRcv)
              THEN SendAllFrom(sentMsg, n)
              ELSE sentMsg

ReceiveMsgC(n, s) ==
  /\ n \in FaultC
  /\ s \in Node
  /\ sentMsg[s][n]
  /\ \E send \in BOOLEAN :
       LET newRcv == [rcvMsg EXCEPT ![s][n] = TRUE] IN
         /\ rcvMsg' = newRcv
         /\ accept' =
              IF HasBQuorumRcv(n, newRcv)
                THEN [accept EXCEPT ![n] = TRUE]
                ELSE accept
         /\ sentMsg' =
              IF HasAQuorumRcv(n, newRcv) /\ send
                THEN SendAllFrom(sentMsg, n)
                ELSE sentMsg

ReceiveInitI(n) ==
  /\ n \in FaultI
  /\ n \in RcvInit
  /\ \E newRow \in [Node -> BOOLEAN] :
       /\ \A dst \in Node : sentMsg[n][dst] => newRow[dst]
       /\ sentMsg' = [sentMsg EXCEPT ![n] = newRow]
  /\ UNCHANGED << accept, rcvMsg >>

ReceiveMsgI(n, s) ==
  /\ n \in FaultI
  /\ s \in Node
  /\ sentMsg[s][n]
  /\ LET newRcv == [rcvMsg EXCEPT ![s][n] = TRUE] IN
       /\ rcvMsg' = newRcv
       /\ accept' =
            IF HasBQuorumRcv(n, newRcv)
              THEN [accept EXCEPT ![n] = TRUE]
              ELSE accept
       /\ \E newRow \in [Node -> BOOLEAN] :
            /\ IF HasAQuorumRcv(n, newRcv)
                 THEN \A dst \in Node : sentMsg[n][dst] => newRow[dst]
                 ELSE newRow = sentMsg[n]
            /\ sentMsg' = [sentMsg EXCEPT ![n] = newRow]

FaultySendS(n) ==
  /\ n \in FaultS
  /\ sentMsg' = SendAllFrom(sentMsg, n)
  /\ UNCHANGED << accept, rcvMsg >>

FaultyStateSA(n) ==
  /\ n \in (FaultS \cup FaultA)
  /\ \E newAccept \in BOOLEAN :
     \E newCol \in [Node -> BOOLEAN] :
       /\ accept' = [accept EXCEPT ![n] = newAccept]
       /\ rcvMsg' = SetReceiveColumn(rcvMsg, n, newCol)
  /\ UNCHANGED sentMsg

FaultySendA(n) ==
  /\ n \in FaultA
  /\ \E newRow \in [Node -> BOOLEAN] :
       /\ \A dst \in Node : sentMsg[n][dst] => newRow[dst]
       /\ sentMsg' = [sentMsg EXCEPT ![n] = newRow]
  /\ UNCHANGED << accept, rcvMsg >>

Next ==
  \/ \E n \in Node : ReceiveInit(n)
  \/ \E n, s \in Node : ReceiveMsg(n, s)
  \/ \E n, s \in Node : ReceiveMsgC(n, s)
  \/ \E n \in Node : ReceiveInitI(n)
  \/ \E n, s \in Node : ReceiveMsgI(n, s)
  \/ \E n \in Node : FaultySendS(n)
  \/ \E n \in Node : FaultyStateSA(n)
  \/ \E n \in Node : FaultySendA(n)

SafetySpec ==
  /\ Init
  /\ [][Next]_vars

=============================================================================
