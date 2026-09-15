---- MODULE GermanData ----
EXTENDS GermanDataDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => []DataProp
\* BEGIN AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_DataProp.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_DataProp.tla

THEOREM Spec => []TransactionConsistency
\* BEGIN AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_TransactionConsistency.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_TransactionConsistency.tla

THEOREM Spec => []DirectoryAccurate
\* BEGIN AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_DirectoryAccurate.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_DirectoryAccurate.tla

THEOREM Spec => []ExclusiveIsolation
\* BEGIN AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_ExclusiveIsolation.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_ExclusiveIsolation.tla

THEOREM Spec => []WritebackCarriesLatest
\* BEGIN AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_WritebackCarriesLatest.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_WritebackCarriesLatest.tla

THEOREM Spec => Refinement
\* BEGIN AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_Refinement.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_GermanProtocol/GermanData_Refinement.tla
====
