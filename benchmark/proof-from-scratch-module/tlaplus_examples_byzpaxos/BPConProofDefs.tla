---------------------------- MODULE BPConProofDefs ------------------------------

EXTENDS BPConProofModel

1aMessage == [type : {"1a"},  bal : Ballot]

1cMessage ==

  [type : {"1c"}, bal : Ballot, val : Value]

BMessage ==
  1aMessage \cup 1bMessage \cup 1cMessage \cup 2avMessage \cup 2bMessage

Quorum == {S \cap Acceptor : S \in ByzQuorum}

msgsOfType(t) == {m \in bmsgs : m.type = t }

acceptorMsgsOfType(t) == {m \in msgsOfType(t) : m.acc \in  Acceptor}

1bRestrict(m) == [type |-> "1b", acc |-> m.acc, bal |-> m.bal,
                  mbal |-> m.mbal, mval |-> m.mval]

1bmsgs == { 1bRestrict(m) : m \in acceptorMsgsOfType("1b") }

1cmsgs == {m \in msgsOfType("1c") :
                   \E a \in Acceptor : KnowsSafeAt(a, m.bal, m.val)}

2amsgs == {m \in [type : {"2a"}, bal : Ballot, val : Value] :
             \E Q \in Quorum :
               \A a \in Q :
                 \E m2av \in acceptorMsgsOfType("2av") :
                    /\ m2av.acc = a
                    /\ m2av.bal = m.bal
                    /\ m2av.val = m.val }

msgs == msgsOfType("1a") \cup 1bmsgs \cup 1cmsgs \cup 2amsgs
         \cup acceptorMsgsOfType("2b")

MaxBallot(S) ==
  IF S = {} THEN -1
            ELSE CHOOSE mb \in S : \A x \in S : mb  >= x

1bOr2bMsgs == {m \in bmsgs : m.type \in {"1b", "2b"}}

PmaxBal == [a \in Acceptor |->
              MaxBallot({m.bal : m \in {ma \in 1bOr2bMsgs :
                                           ma.acc = a}})]

P == INSTANCE PConProof WITH maxBal <- PmaxBal

TypeOK == /\ maxBal  \in [Acceptor -> Ballot \cup {-1}]
          /\ 2avSent \in [Acceptor -> SUBSET [val : Value, bal : Ballot]]
          /\ maxVBal \in [Acceptor -> Ballot \cup {-1}]
          /\ maxVVal \in [Acceptor -> Value \cup {None}]
          /\ knowsSent \in [Acceptor -> SUBSET 1bMessage]
          /\ bmsgs \subseteq BMessage

bmsgsFinite == IsFiniteSet(1bOr2bMsgs)

1bInv1 == \A m \in bmsgs  :
             /\ m.type = "1b"
             /\ m.acc \in Acceptor
             => \A r \in m.m2av :
                [type |-> "1c", bal |-> r.bal, val |-> r.val] \in msgs

1bInv2 == \A m1, m2 \in bmsgs  :
             /\ m1.type = "1b"
             /\ m2.type = "1b"
             /\ m1.acc \in Acceptor
             /\ m1.acc = m2.acc
             /\ m1.bal = m2.bal
             => m1 = m2

2avInv1 == \A m1, m2 \in bmsgs :
             /\ m1.type = "2av"
             /\ m2.type = "2av"
             /\ m1.acc \in Acceptor
             /\ m1.acc = m2.acc
             /\ m1.bal = m2.bal
             => m1 = m2

2avInv2 == \A m \in bmsgs :
             /\ m.type = "2av"
             /\ m.acc \in Acceptor
             => \E r \in 2avSent[m.acc] : /\ r.val = m.val
                                          /\ r.bal >= m.bal

2avInv3 == \A m \in bmsgs :
             /\ m.type = "2av"
             /\ m.acc \in Acceptor
             => [type |-> "1c", bal |-> m.bal, val |-> m.val] \in msgs

maxBalInv == \A m \in bmsgs :
               /\ m.type \in {"1b", "2av", "2b"}
               /\ m.acc \in Acceptor
               => m.bal =< maxBal[m.acc]

accInv == \A a \in Acceptor :
            \A r \in 2avSent[a] :
              /\ r.bal =< maxBal[a]
              /\ [type |-> "1c", bal |-> r.bal, val |-> r.val] \in msgs

knowsSentInv == \A a \in Acceptor : knowsSent[a] \subseteq msgsOfType("1b")

Inv ==
 TypeOK /\ bmsgsFinite /\ 1bInv1 /\ 1bInv2 /\ maxBalInv  /\ 2avInv1 /\ 2avInv2
   /\ 2avInv3 /\ accInv /\ knowsSentInv

chosen == {v \in Value : \E BQ \in ByzQuorum, b \in Ballot :
                           \A a \in BQ : \E m \in msgs : /\ m.type = "2b"
                                                         /\ m.acc  = a
                                                         /\ m.bal  = b
                                                         /\ m.val  = v}

==============================================================================
