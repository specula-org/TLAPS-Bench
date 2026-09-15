---------------------------- MODULE FindHighestDefs -----------------------------

EXTENDS FindHighestModel

TypeOK ==
  /\ f \in Seq(Nat)
  /\ i \in 1..(Len(f) + 1)
  /\ i \in Nat
  /\ h \in Nat \cup {-1}

InductiveInvariant ==
  \A idx \in 1..(i - 1) : f[idx] <= h

DoneIndexValue == pc = "Done" => i = Len(f) + 1

Correctness ==
  pc = "Done" =>
    \A idx \in DOMAIN f : f[idx] <= h

=============================================================================

