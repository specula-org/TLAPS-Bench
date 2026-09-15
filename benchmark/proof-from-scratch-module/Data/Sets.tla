---- MODULE Sets ----
EXTENDS SetsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM CardinalityTwo == \A m, p : m # p => 
                              /\ IsFiniteSet({m,p})
                              /\ Cardinality({m,p}) = 2
\* BEGIN AGENT PROOF Data/Sets_CardinalityTwo.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_CardinalityTwo.tla

THEOREM IntervalCardinality ==  
  ASSUME NEW a \in Nat, NEW b \in Nat 
  PROVE  /\ IsFiniteSet(a..b)
         /\ Cardinality(a..b) = IF a > b THEN 0 ELSE b-a+1
\* BEGIN AGENT PROOF Data/Sets_IntervalCardinality.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_IntervalCardinality.tla

THEOREM CardinalityOneConverse ==
   ASSUME NEW S, IsFiniteSet(S), Cardinality(S) = 1
   PROVE  \E m : S = {m}
\* BEGIN AGENT PROOF Data/Sets_CardinalityOneConverse.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_CardinalityOneConverse.tla

THEOREM IsBijectionInverse ==
  ASSUME NEW f, NEW S, NEW T, 
         IsBijection(f, S, T) 
  PROVE  \E g : IsBijection(g, T, S)
\* BEGIN AGENT PROOF Data/Sets_IsBijectionInverse.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_IsBijectionInverse.tla

THEOREM IsBijectionTransitive ==
  ASSUME NEW f1, NEW f2, NEW S, NEW T, NEW U, 
           IsBijection(f1, S, U),
           IsBijection(f2, U, T) 
  PROVE  \E g : IsBijection(g, S, T)
\* BEGIN AGENT PROOF Data/Sets_IsBijectionTransitive.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_IsBijectionTransitive.tla

THEOREM FiniteSubset ==
  ASSUME NEW S, NEW TT, IsFiniteSet(TT), S \subseteq TT
  PROVE  /\ IsFiniteSet(S)
         /\ Cardinality(S) \leq Cardinality(TT)
\* BEGIN AGENT PROOF Data/Sets_FiniteSubset.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_FiniteSubset.tla

THEOREM PigeonHole ==
            \A S, T : /\ IsFiniteSet(S)
                      /\ IsFiniteSet(T)
                      /\ Cardinality(T) < Cardinality(S)
                      => \A f \in [S -> T] :
                           \E x, y \in S : x # y /\ f[x] = f[y]
\* BEGIN AGENT PROOF Data/Sets_PigeonHole.tla
PROOF OMITTED
\* END AGENT PROOF Data/Sets_PigeonHole.tla
====
