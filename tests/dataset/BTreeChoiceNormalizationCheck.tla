---- MODULE BTreeChoiceNormalizationCheck ----
EXTENDS TLAPS

CONSTANT Nodes
VARIABLE free

EmptyChoice == CHOOSE x : FALSE
Pick(S) == IF S = {} THEN EmptyChoice ELSE CHOOSE x \in S : TRUE

THEOREM ChooseBySet ==
  ASSUME NEW S, NEW P(_)
  PROVE (CHOOSE x \in S : P(x)) =
        (CHOOSE x \in {y \in S : P(y)} : TRUE)
BY Zenon

THEOREM EmptyChoiceCase ==
  ASSUME NEW S, S = {}
  PROVE (CHOOSE x \in S : TRUE) = EmptyChoice
BY Zenon DEF EmptyChoice

THEOREM PickEquivalent ==
  ASSUME NEW S
  PROVE Pick(S) = (CHOOSE x \in S : TRUE)
BY Zenon DEF Pick, EmptyChoice

THEOREM FreeNodeEquivalent ==
  (CHOOSE n \in Nodes : n \in free) = Pick({n \in Nodes : n \in free})
BY ChooseBySet, PickEquivalent

THEOREM DistinctFreeNodeEquivalent ==
  ASSUME NEW n2
  PROVE (CHOOSE n \in Nodes : n \in free /\ n # n2) =
        Pick({n \in Nodes : n \in free /\ n # n2})
BY ChooseBySet, PickEquivalent
====
