---- MODULE Cantor1 ----
EXTENDS Cantor1Defs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM cantor ==
  \A S :
    \A f \in [S -> SUBSET S] :
      \E A \in SUBSET S :
        \A x \in S :
          f [x] # A
\* BEGIN AGENT PROOF Cantor/Cantor1_cantor.tla
PROOF OMITTED
\* END AGENT PROOF Cantor/Cantor1_cantor.tla
====
