------------------------- MODULE StorageArithmetic -------------------------
EXTENDS Storage, TLAPS

\* Locally checked form of the standard natural-number induction principle.
THEOREM NaturalInduction ==
  ASSUME NEW P(_), P(0), \A n \in Nat : P(n) => P(n+1)
  PROVE \A n \in Nat : P(n)
BY IsaM("(intro natInduct, auto)")

THEOREM BoundedMaximumExists ==
  \A b \in Nat : \A S \in SUBSET (0..b) :
    S # {} => \E m \in S : \A x \in S : m >= x
<1> DEFINE P(b) == \A S \in SUBSET (0..b) :
                    S # {} => \E m \in S : \A x \in S : m >= x
<1>1. P(0) BY SMT DEF P
<1>2. \A b \in Nat : P(b) => P(b+1)
  <2>1. ASSUME NEW b \in Nat, NEW S \in SUBSET (0..(b+1)), P(b), S # {}
        PROVE \E m \in S : \A x \in S : m >= x
    <3>1. CASE b+1 \in S
      BY SMT, <2>1, <3>1
    <3>2. CASE b+1 \notin S
      <4>1. S \subseteq 0..b BY SMT, <2>1, <3>2
      <4> QED BY SMT, <2>1, <4>1 DEF P
    <3> QED BY SMT, <3>1, <3>2
  <2> QED BY SMT, <2>1 DEF P
<1>3. \A b \in Nat : P(b) BY <1>1, <1>2, NaturalInduction, Isa
<1> QED BY SMT, <1>3 DEF P

THEOREM BoundedMaximum ==
  ASSUME NEW b \in Nat, NEW S \in SUBSET (0..b), S # {}
  PROVE /\ Max(S) \in S
        /\ \A x \in S : Max(S) >= x
BY SMT, BoundedMaximumExists DEF Max
=============================================================================
