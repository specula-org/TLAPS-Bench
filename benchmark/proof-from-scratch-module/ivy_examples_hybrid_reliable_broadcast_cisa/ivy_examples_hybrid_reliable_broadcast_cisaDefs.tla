---------------- MODULE ivy_examples_hybrid_reliable_broadcast_cisaDefs ----------------
EXTENDS ivy_examples_hybrid_reliable_broadcast_cisaModel

CorrectReceiveInit(n) ==
  /\ Correct(n)
  /\ ReceiveInit(n)

CorrectReceiveMsg(n, s) ==
  /\ Correct(n)
  /\ ReceiveMsg(n, s)

Spec ==
  /\ SafetySpec
  /\ \A n \in Node :
       (Correct(n) /\ n \in RcvInit) => WF_vars(CorrectReceiveInit(n))
  /\ \A n, s \in Node :
       Correct(n) => WF_vars(CorrectReceiveMsg(n, s))

Unforgeability ==
  (\E n \in Node : Obedient(n) /\ accept[n]) =>
  (\E m \in Node : Obedient(m) /\ m \in RcvInit)

AllObedientInit ==
  \A n \in Node : Obedient(n) => n \in RcvInit

SomeCorrectAccepts ==
  \E n \in Node : Correct(n) /\ accept[n]

Correctness ==
  AllObedientInit => <>SomeCorrectAccepts

SomeObedientAccepts ==
  \E n \in Node : Obedient(n) /\ accept[n]

AllCorrectAccept ==
  \A n \in Node : Correct(n) => accept[n]

Relay ==
  <>SomeObedientAccepts => <>AllCorrectAccept

=============================================================================
