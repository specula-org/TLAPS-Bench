---- MODULE VictimRouting ----
EXTENDS ShadowEntry
CONSTANTS SenderLocal, Shadowed
VARIABLE done

Sender == IF SenderLocal THEN "p0" ELSE "q"
Ack == [type |-> "VictimAck", cmdr |-> Sender, adr |-> "a"]
Clear == [type |-> "ShadowClear", cmdr |-> Sender, adr |-> "a"]
VictimMsg == [type |-> "Victim", cmdr |-> Sender, adr |-> "a", data |-> ZeroBits]
EmptyQueues == [ProcToLS |-> [p \in Proc |-> <<>>],
                LSToProc |-> [p \in Proc |-> <<>>],
                LSToGS |-> [ls \in LS |-> <<>>],
                GSToLS |-> [ls \in LS |-> <<>>]]
InputQueues == IF Shadowed
               THEN [EmptyQueues EXCEPT !.GSToLS["ls0"] = <<{Clear}>>]
               ELSE EmptyQueues

\* A local transition test, not a claim that this entire state is reachable.
RoutingInit ==
  /\ done = FALSE
  /\ Q = InputQueues
  /\ memDir = [a \in Adr |-> [data |-> ZeroBits, writer |-> InMemory, readers |-> {}]]
  /\ cache = [p \in Proc |-> [a \in Adr |->
       [state |-> "Invalid", fillOrCTEAckPending |-> FALSE, version |-> <<>>]]]
  /\ reqQ = [p \in Proc |-> <<>>]
  /\ respQ = [p \in Proc |-> <<>>]
  /\ locked = [p \in Proc |-> Unlocked]
  /\ fillQ = [p \in Proc |-> {}]
  /\ aInt = [reqs |-> [p \in Proc |-> <<>>], resps |-> [p \in Proc |-> <<>>]]

RoutingNext == /\ ~done
               /\ DirectoryProcessVictim(VictimMsg, "ls0", Q)
               /\ done' = TRUE

RoutingCorrect == done =>
  IF Shadowed THEN Q.LSToGS["ls0"] = <<{Ack, Clear}>> /\ Q.LSToProc[Sender] = <<>>
  ELSE IF SenderLocal THEN Q.LSToProc[Sender] = <<{Ack}>> /\ Q.LSToGS["ls0"] = <<>>
       ELSE Q.LSToGS["ls0"] = <<{Ack}>> /\ Q.LSToProc[Sender] = <<>>
====
