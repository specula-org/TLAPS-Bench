---- MODULE Cantor5 ----
EXTENDS Cantor5Defs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM cantor ==
  \A S, f :
    \E A \in SUBSET S :
      \A x \in S :
        f [x] # A
\* BEGIN AGENT PROOF Cantor/Cantor5_cantor.tla
PROOF OMITTED
\* END AGENT PROOF Cantor/Cantor5_cantor.tla
====
