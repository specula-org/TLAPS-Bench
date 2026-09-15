------------------------------- MODULE CRDT ---------------------------------

EXTENDS Naturals, FiniteSets

CONSTANT Node
ASSUME NodeAssumption == IsFiniteSet(Node)

VARIABLE counter
vars == counter

TypeOK == counter \in [Node -> [Node -> Nat]]

Safety == \A n, o \in Node : counter[n][n] >= counter[o][n]

Monotonic == \A n, o \in Node : counter'[n][o] >= counter[n][o]

Monotonicity == [][Monotonic]_counter

Convergence == []<>(\A n, o \in Node : counter[n] = counter[o])

Init == counter = [n \in Node |-> [o \in Node |-> 0]]

Increment(n) == counter' = [counter EXCEPT ![n][n] = @ + 1]

Gossip(n, o) ==
  LET Max(a, b) == IF a > b THEN a ELSE b IN
  counter' = [
    counter EXCEPT ![o] = [
      nodeView \in Node |->
        Max(counter[n][nodeView], counter[o][nodeView])
      ]
    ]

Next ==
  \/ \E n \in Node : Increment(n)
  \/ \E n, o \in Node : Gossip(n, o)

Spec ==
  /\ Init
  /\ [][Next]_counter

-----------------------------------------------------------------------------

Fairness ==
    /\ \A n, o \in Node : WF_vars(Gossip(n,o))
    /\ <>[][\E n, o \in Node : Gossip(n,o)]_vars

FairSpec ==
  /\ Spec
  /\ Fairness

=============================================================================

