---- MODULE CCFProof_CommittedLogsAppendOnly ----
EXTENDS CCFProof_CommittedLogsAppendOnlyDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM CommittedLogsAppendOnly == Spec => CommittedLogAppendOnlyProp
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
