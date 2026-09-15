---- MODULE Cantor9 ----
EXTENDS Cantor9Defs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Cantor ==
  ~ \E f : Surj (f, SUBSET (DOMAIN f))
\* BEGIN AGENT PROOF Cantor/Cantor9_Cantor.tla
PROOF OMITTED
\* END AGENT PROOF Cantor/Cantor9_Cantor.tla
====
