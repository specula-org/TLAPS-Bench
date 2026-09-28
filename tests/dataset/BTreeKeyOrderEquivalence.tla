---- MODULE BTreeKeyOrderEquivalence ----
EXTENDS TLAPS, Relation

\* These definitions isolate the standard modules' comparison semantics:
\* Specifying Systems, Figures 18.5b and 18.6. RealReflexive follows from the
\* real-order axioms; InfinityDomains is the defining choice of infinities.
CONSTANTS RealDomain, RealOrder, PlusInfinity, MinusInfinity, Keys
ASSUME RealReflexive == \A a \in RealDomain : <<a,a>> \in RealOrder
ASSUME InfinityDomains == /\ PlusInfinity \notin RealDomain
                          /\ MinusInfinity \notin RealDomain \cup {PlusInfinity}
BookLE(a,b) == CASE (a \in RealDomain) /\ (b \in RealDomain) -> <<a,b>> \in RealOrder
                [] (a = PlusInfinity) /\ (b \in RealDomain \cup {MinusInfinity}) -> FALSE
                [] (a \in RealDomain \cup {MinusInfinity}) /\ (b = PlusInfinity) -> TRUE
                [] a = b -> TRUE
BookGE(a,b) == BookLE(b,a)
BookLT(a,b) == BookLE(a,b) /\ a # b
ASSUME KeyOrder == IsStrictlyTotallyOrderedUnder(BookLT, Keys)

GuardedGE(a,b) == IF a \in Keys /\ b \in Keys THEN ~BookLT(a,b) ELSE BookGE(a,b)

THEOREM ReflexiveAtEveryValue ==
  ASSUME NEW a
  PROVE BookGE(a,a)
BY RealReflexive, InfinityDomains, Zenon DEF BookGE, BookLE

THEOREM KeyComparisonEquivalent ==
  ASSUME NEW a \in Keys, NEW b \in Keys
  PROVE BookGE(a,b) <=> ~BookLT(a,b)
<1>1. a = b \/ BookLT(a,b) \/ BookLT(b,a)
  BY KeyOrder, Zenon DEF IsStrictlyTotallyOrderedUnder, IsStrictlyTotallyOrdered
<1>2. ~(BookLT(a,b) /\ BookLT(b,a))
  BY KeyOrder, Zenon
    DEF IsStrictlyTotallyOrderedUnder, IsStrictlyTotallyOrdered,
        IsStrictlyPartiallyOrdered, IsAntiSymmetric, IsIrreflexive
<1>3. CASE a = b
  BY <1>3, ReflexiveAtEveryValue, Zenon DEF BookLT, BookGE
<1>4. CASE a # b
  BY <1>1, <1>2, <1>4, Zenon DEF BookLT, BookGE
<1> QED BY <1>3, <1>4

THEOREM EveryComparisonContextEquivalent ==
  ASSUME NEW a, NEW b, NEW yes, NEW no
  PROVE (IF GuardedGE(a,b) THEN yes ELSE no) =
        (IF BookGE(a,b) THEN yes ELSE no)
BY KeyComparisonEquivalent, Zenon DEF GuardedGE

THEOREM EmptyOrNonemptySearchBranchEquivalent ==
  ASSUME NEW empty, NEW a, NEW b, NEW lastChild, NEW nextChild
  PROVE (IF empty \/ GuardedGE(a,b) THEN lastChild ELSE nextChild) =
        (IF empty \/ BookGE(a,b) THEN lastChild ELSE nextChild)
BY KeyComparisonEquivalent, Zenon DEF GuardedGE

THEOREM SplitPartitionEquivalent ==
  ASSUME NEW keys, NEW pivot
  PROVE {x \in keys : GuardedGE(x,pivot)} = {x \in keys : BookGE(x,pivot)}
BY KeyComparisonEquivalent, Zenon DEF GuardedGE
====
