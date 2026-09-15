---------------------------- MODULE PConProof -------------------------------

EXTENDS Integers, TLAPS
-----------------------------------------------------------------------------

CONSTANT Value, Acceptor, Quorum

ASSUME QA == /\ \A Q \in Quorum : Q \subseteq Acceptor 
             /\ \A Q1, Q2 \in Quorum : Q1 \cap Q2 # {} 
                                                                     
Ballot == Nat

ASSUME BallotAssump == (Ballot \cup {-1}) \cap Acceptor = {}

None == CHOOSE v : v \notin Value

-----------------------------------------------------------------------------

VARIABLES maxBal, maxVBal, maxVVal, msgs

sentMsgs(t, b) == {m \in msgs : (m.type = t) /\ (m.bal = b)}

ShowsSafeAt(Q, b, v) ==
  LET Q1b == {m \in sentMsgs("1b", b) : m.acc \in Q}
  IN  /\ \A a \in Q : \E m \in Q1b : m.acc = a
      /\ \/ \A m \in Q1b : m.mbal = -1
         \/ \E m1c \in msgs :
              /\ m1c = [type |-> "1c", bal |-> m1c.bal, val |-> v]
              /\ \A m \in Q1b : /\ m1c.bal \geq m.mbal
                                /\ (m1c.bal = m.mbal) => (m.mval = v)

vars == << maxBal, maxVBal, maxVVal, msgs >>

Init == 
        /\ maxBal = [a \in Acceptor |-> -1]
        /\ maxVBal = [a \in Acceptor |-> -1]
        /\ maxVVal = [a \in Acceptor |-> None]
        /\ msgs = {}

acceptor(self) == \E b \in Ballot:
                    \/ /\ (b > maxBal[self]) /\ (sentMsgs("1a", b) # {})
                       /\ maxBal' = [maxBal EXCEPT ![self] = b]
                       /\ msgs' = (msgs \cup {([type |-> "1b", acc |-> self, bal |-> b,
                                                       mbal |-> maxVBal[self], mval |-> maxVVal[self]])})
                       /\ UNCHANGED <<maxVBal, maxVVal>>
                    \/ /\ b \geq maxBal[self]
                       /\ \E m \in sentMsgs("2a", b):
                            /\ maxBal' = [maxBal EXCEPT ![self] = b]
                            /\ maxVBal' = [maxVBal EXCEPT ![self] = b]
                            /\ maxVVal' = [maxVVal EXCEPT ![self] = m.val]
                            /\ msgs' = (msgs \cup {([type |-> "2b", acc |-> self, bal |-> b, val |-> m.val])})

leader(self) == /\ \/ /\ msgs' = (msgs \cup {([type |-> "1a", bal |-> self])})
                   \/ /\ \E S \in SUBSET Value:
                           /\ \A v \in S : \E Q \in Quorum : ShowsSafeAt(Q, self, v)
                           /\ msgs' = (msgs \cup ({[type |-> "1c", bal |-> self, val |-> v] : v \in S}))
                   \/ /\ \E v \in Value:
                           /\ /\ sentMsgs("2a", self) = {}
                              /\ [type |-> "1c", bal |-> self, val |-> v] \in msgs
                           /\ msgs' = (msgs \cup {([type |-> "2a", bal |-> self, val |-> v])})
                /\ UNCHANGED << maxBal, maxVBal, maxVVal >>

Next == (\E self \in Acceptor: acceptor(self))
           \/ (\E self \in Ballot: leader(self))

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

chosen == {v \in Value : \E Q \in Quorum, b \in Ballot :
                           \A a \in Q : \E m \in msgs : /\ m.type = "2b"
                                                        /\ m.acc  = a
                                                        /\ m.bal  = b
                                                        /\ m.val  = v} 
----------------------------------------------------------------------------

votes == [a \in Acceptor |->  
           {<<m.bal, m.val>> : m \in {mm \in msgs: /\ mm.type = "2b"
                                                   /\ mm.acc = a }}]

V == INSTANCE VoteProof 

-----------------------------------------------------------------------------

=============================================================================
