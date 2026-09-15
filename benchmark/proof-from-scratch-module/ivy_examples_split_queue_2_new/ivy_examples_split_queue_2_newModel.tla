-------------------------- MODULE ivy_examples_split_queue_2_newModel --------------------------
EXTENDS Naturals, TLAPS

VARIABLES begun, done, queue, firstq

vars == << begun, done, queue, firstq >>

HasUndoneFrom(b, d) ==
  \E x \in Nat : b[x] /\ ~d[x]

FirstUndoneFrom(x, b, d) ==
  /\ x \in Nat
  /\ b[x]
  /\ ~d[x]
  /\ \A y \in Nat : (b[y] /\ ~d[y]) => x <= y

UpdateFirstq(b, d) ==
  IF HasUndoneFrom(b, d)
    THEN FirstUndoneFrom(firstq', b, d)
    ELSE firstq' = firstq

Init ==
  /\ begun = [x \in Nat |-> FALSE]
  /\ done = [x \in Nat |-> FALSE]
  /\ queue \in [Nat -> BOOLEAN]
  /\ firstq = 0

Send(lt, kind) ==
  /\ lt \in Nat
  /\ kind \in BOOLEAN
  /\ \A x \in Nat : begun[x] => x < lt
  /\ begun' = [begun EXCEPT ![lt] = TRUE]
  /\ queue' = [queue EXCEPT ![lt] = kind]
  /\ UpdateFirstq(begun', done)
  /\ UNCHANGED done

Recv1 ==
  \E x \in Nat :
    /\ FirstUndoneFrom(x, begun, done)
    /\ queue[x]
    /\ done' = [done EXCEPT ![x] = TRUE]
    /\ UpdateFirstq(begun, done')
    /\ UNCHANGED << begun, queue >>

Recv2 ==
  \E x \in Nat :
    /\ FirstUndoneFrom(x, begun, done)
    /\ ~queue[x]
    /\ done' = [done EXCEPT ![x] = TRUE]
    /\ UpdateFirstq(begun, done')
    /\ UNCHANGED << begun, queue >>

Next ==
  \/ \E lt \in Nat, kind \in BOOLEAN : Send(lt, kind)
  \/ Recv1
  \/ Recv2

SafetySpec ==
  /\ Init
  /\ [][Next]_vars

Spec ==
  /\ SafetySpec
  /\ WF_vars(Recv1)
  /\ WF_vars(Recv2)

===========================================================================================
