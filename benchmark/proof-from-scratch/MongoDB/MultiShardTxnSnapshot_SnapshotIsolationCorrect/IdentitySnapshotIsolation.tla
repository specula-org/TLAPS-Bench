---------------------- MODULE IdentitySnapshotIsolation ----------------------
EXTENDS Naturals, Sequences, FiniteSets, Util

CONSTANTS Keys, Values

Operation == [op : {"read", "write"}, key : Keys, value : Values]

WellFormed(initial, transactions) ==
  /\ initial \in [Keys -> Values]
  /\ IsFiniteSet(transactions)
  /\ \A t \in transactions : t.ops \in Seq(Operation)
  /\ \A t, u \in transactions : t.id = u.id => t = u

Orders(transactions) == PermSeqs(transactions)

OperationStates(initial, operations) ==
  LET states[i \in 0..Len(operations)] ==
        IF i = 0 THEN initial
        ELSE IF operations[i].op = "write"
             THEN [states[i-1] EXCEPT ![operations[i].key] = operations[i].value]
             ELSE states[i-1]
  IN states

Effects(initial, operations) == OperationStates(initial,operations)[Len(operations)]

ExecutionStates(initial, order) ==
  LET states[j \in 0..Len(order)] ==
        IF j = 0 THEN initial
        ELSE Effects(states[j-1],order[j].ops)
  IN states

WriteKeys(operations) ==
  {operations[i].key : i \in {j \in 1..Len(operations) : operations[j].op = "write"}}

Complete(snapshot, operations) ==
  LET localStates == OperationStates(snapshot,operations) IN
  \A i \in 1..Len(operations) :
    operations[i].op = "read" =>
      operations[i].value = localStates[i-1][operations[i].key]

NoConf(order, transactionPosition, cut) ==
  \A j \in (cut+1)..(transactionPosition-1) :
    WriteKeys(order[j].ops) \cap WriteKeys(order[transactionPosition].ops) = {}

SnapshotAt(states, order, transactionPosition, cut) ==
  /\ cut \in 0..(transactionPosition-1)
  /\ Complete(states[cut],order[transactionPosition].ops)
  /\ NoConf(order,transactionPosition,cut)

ExecutionSatisfiesSI(initial, order) ==
  LET states == ExecutionStates(initial,order) IN
  \A j \in 1..Len(order) : \E cut \in 0..(j-1) : SnapshotAt(states,order,j,cut)

SnapshotIsolation(initial, transactions) ==
  /\ WellFormed(initial,transactions)
  /\ \E order \in Orders(transactions) : ExecutionSatisfiesSI(initial,order)
=============================================================================
