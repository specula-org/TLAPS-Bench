---- MODULE CCFProof ----
EXTENDS CCFProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM CommittedLogsAgree == Spec => []LogInv
\* BEGIN AGENT PROOF CCF/CCFProof_CommittedLogsAgree.tla
PROOF OMITTED
\* END AGENT PROOF CCF/CCFProof_CommittedLogsAgree.tla

THEOREM CommittedLogsAppendOnly == Spec => CommittedLogAppendOnlyProp
\* BEGIN AGENT PROOF CCF/CCFProof_CommittedLogsAppendOnly.tla
PROOF OMITTED
\* END AGENT PROOF CCF/CCFProof_CommittedLogsAppendOnly.tla
====
