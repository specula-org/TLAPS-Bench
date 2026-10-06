---- MODULE SlateDBWALProof ----
EXTENDS SlateDBWALProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOKInvariant == Spec => []TypeOK
\* BEGIN AGENT PROOF SlateDBWAL/SlateDBWALProof_TypeOKInvariant.tla
PROOF OMITTED
\* END AGENT PROOF SlateDBWAL/SlateDBWALProof_TypeOKInvariant.tla

THEOREM ValidWritersInvariant == Spec => []ValidWriters
\* BEGIN AGENT PROOF SlateDBWAL/SlateDBWALProof_ValidWritersInvariant.tla
PROOF OMITTED
\* END AGENT PROOF SlateDBWAL/SlateDBWALProof_ValidWritersInvariant.tla

THEOREM ConsistentMachineDataInvariant == Spec => []ConsistentMachineData
\* BEGIN AGENT PROOF SlateDBWAL/SlateDBWALProof_ConsistentMachineDataInvariant.tla
PROOF OMITTED
\* END AGENT PROOF SlateDBWAL/SlateDBWALProof_ConsistentMachineDataInvariant.tla

THEOREM ManifestRepresentsCommittedLogInvariant == Spec => []ManifestRepresentsCommittedLog
\* BEGIN AGENT PROOF SlateDBWAL/SlateDBWALProof_ManifestRepresentsCommittedLogInvariant.tla
PROOF OMITTED
\* END AGENT PROOF SlateDBWAL/SlateDBWALProof_ManifestRepresentsCommittedLogInvariant.tla
====
