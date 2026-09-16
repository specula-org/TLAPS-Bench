-------------------------- MODULE IdentitySIControls --------------------------
EXTENDS IdentitySnapshotIsolation, TLC
VARIABLE tick

Initial == [k \in Keys |-> 0]
Read(k,v) == [op |-> "read", key |-> k, value |-> v]
Write(k,v) == [op |-> "write", key |-> k, value |-> v]
Transaction(id,operations) == [id |-> id, ops |-> operations]

EmptyTransactions == SnapshotIsolation(Initial,{})
EmptyIdentities ==
  LET txs == {Transaction("e1",<<>>),Transaction("e2",<<>>)} IN
    /\ Cardinality(Orders(txs)) = 2
    /\ \A order \in Orders(txs) : Len(order) = 2
    /\ SnapshotIsolation(Initial,txs)
EqualReadHistories == SnapshotIsolation(Initial,{
  Transaction("r1",<<Read("x",0)>>),Transaction("r2",<<Read("x",0)>>)})
DuplicateDeleteRegression == SnapshotIsolation(Initial,{
  Transaction("A",<<Write("x",1),Write("y",1)>>),
  Transaction("D1",<<Write("x",0)>>),
  Transaction("B",<<Read("y",1),Read("x",0),Write("x",2),Write("z",2)>>),
  Transaction("D2",<<Write("x",0)>>),
  Transaction("R",<<Read("z",2),Read("x",0)>>)})
LatestOwnWrite == SnapshotIsolation(Initial,{
  Transaction("t",<<Write("x",1),Read("x",1),Write("x",2),Read("x",2)>>)})
StaleOwnWriteRejected == ~SnapshotIsolation(Initial,{
  Transaction("t",<<Write("x",1),Write("x",2),Read("x",1)>>)})
ReadBeforeOwnWrite == SnapshotIsolation(Initial,{
  Transaction("t",<<Read("x",0),Write("x",1),Read("x",1)>>)})
RepeatedReadOccurrencesRejected == ~SnapshotIsolation(Initial,{
  Transaction("t",<<Read("x",0),Write("x",1),Read("x",0)>>)})
RepeatedReadsAccepted == SnapshotIsolation(Initial,{
  Transaction("t",<<Read("x",0),Read("x",0)>>)})
DirtyReadRejected == ~SnapshotIsolation(Initial,{
  Transaction("reader",<<Read("x",1)>>)})
FuzzyReadRejected == ~SnapshotIsolation(Initial,{
  Transaction("writer",<<Write("x",1)>>),
  Transaction("reader",<<Read("x",0),Read("x",1)>>)})
FracturedReadRejected == ~SnapshotIsolation(Initial,{
  Transaction("writer",<<Write("x",1),Write("y",1)>>),
  Transaction("reader",<<Read("x",1),Read("y",0)>>)})
LostUpdateRejected == ~SnapshotIsolation(Initial,{
  Transaction("t1",<<Read("x",0),Write("x",1)>>),
  Transaction("t2",<<Read("x",0),Write("x",2)>>)})
WriteSkewTransactions == {
  Transaction("t1",<<Read("x",0),Read("y",0),Write("x",1)>>),
  Transaction("t2",<<Read("x",0),Read("y",0),Write("y",2)>>)}
WriteSkewAccepted == SnapshotIsolation(Initial,WriteSkewTransactions)
WriteSkewNotSerializable == ~Serializability(Initial,WriteSkewTransactions)
OrderedEffects == Effects(Initial,<<Write("x",1),Write("x",2)>>)["x"] = 2
IntermediateVersionRejected == ~SnapshotIsolation(Initial,{
  Transaction("writer",<<Write("x",1),Write("x",2)>>),
  Transaction("reader",<<Read("x",1)>>)})
RestoredValueStillConflicts ==
  LET order == <<Transaction("A",<<Write("x",1)>>),
                 Transaction("D",<<Write("x",0)>>),
                 Transaction("T",<<Write("x",2)>>)>>
      states == ExecutionStates(Initial,order)
  IN /\ states[0] = states[2]
     /\ ~NoConf(order,3,0)
     /\ NoConf(order,3,2)
DuplicateIdRejected == ~SnapshotIsolation(Initial,{
  Transaction("same",<<Write("x",1)>>),Transaction("same",<<Write("x",2)>>)})

Init == tick = 0
Next == UNCHANGED tick
=============================================================================
