---- MODULE Cantor8 ----
EXTENDS Cantor8Defs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Cantor ==
  \A S : ~ \E f \in [S -> SUBSET S] : Surj (f, SUBSET S)
\* BEGIN AGENT PROOF Cantor/Cantor8_Cantor.tla
PROOF OMITTED
\* END AGENT PROOF Cantor/Cantor8_Cantor.tla
====
