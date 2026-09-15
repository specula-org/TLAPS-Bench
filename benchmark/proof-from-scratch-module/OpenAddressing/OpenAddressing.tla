---- MODULE OpenAddressing ----
EXTENDS OpenAddressingDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => []CompleteAsSafety
\* BEGIN AGENT PROOF OpenAddressing/OpenAddressing_CompleteAsSafety.tla
PROOF OMITTED
\* END AGENT PROOF OpenAddressing/OpenAddressing_CompleteAsSafety.tla

THEOREM Spec => []Consistent
\* BEGIN AGENT PROOF OpenAddressing/OpenAddressing_Consistent.tla
PROOF OMITTED
\* END AGENT PROOF OpenAddressing/OpenAddressing_Consistent.tla

THEOREM Spec => []Contains
\* BEGIN AGENT PROOF OpenAddressing/OpenAddressing_Contains.tla
PROOF OMITTED
\* END AGENT PROOF OpenAddressing/OpenAddressing_Contains.tla

THEOREM Spec => []Duplicates
\* BEGIN AGENT PROOF OpenAddressing/OpenAddressing_Duplicates.tla
PROOF OMITTED
\* END AGENT PROOF OpenAddressing/OpenAddressing_Duplicates.tla

THEOREM Spec => []Sorted
\* BEGIN AGENT PROOF OpenAddressing/OpenAddressing_Sorted.tla
PROOF OMITTED
\* END AGENT PROOF OpenAddressing/OpenAddressing_Sorted.tla
====
