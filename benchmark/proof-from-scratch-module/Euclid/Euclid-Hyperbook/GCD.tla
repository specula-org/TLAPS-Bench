---- MODULE GCD ----
EXTENDS GCDDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM GCD1 == \A m \in Nat \ {0} : GCD(m, m) = m
\* BEGIN AGENT PROOF Euclid/GCD_GCD1.tla
PROOF OMITTED
\* END AGENT PROOF Euclid/GCD_GCD1.tla

THEOREM GCD2 == \A m, n \in Nat \ {0} : GCD(m, n) = GCD(n, m)
\* BEGIN AGENT PROOF Euclid/GCD_GCD2.tla
PROOF OMITTED
\* END AGENT PROOF Euclid/GCD_GCD2.tla

THEOREM GCD3 == \A m, n \in Nat \ {0} : 
                    (n > m) => (GCD(m, n) = GCD(m, n-m))
\* BEGIN AGENT PROOF Euclid/GCD_GCD3.tla
PROOF OMITTED
\* END AGENT PROOF Euclid/GCD_GCD3.tla
====
