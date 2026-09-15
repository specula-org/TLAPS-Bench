---- MODULE AtomicBakeryWithoutSMT ----
EXTENDS AtomicBakeryWithoutSMTDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == Spec => [] MutualExclusion
\* BEGIN AGENT PROOF AtomicBakery/AtomicBakeryWithoutSMT_Safety.tla
PROOF OMITTED
\* END AGENT PROOF AtomicBakery/AtomicBakeryWithoutSMT_Safety.tla
====
