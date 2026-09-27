---- MODULE SlateDBWALProof_ConsistentMachineDataInvariant ----
EXTENDS SlateDBWALProof_ConsistentMachineDataInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ConsistentMachineDataInvariant == Spec => []ConsistentMachineData
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
