---- MODULE CCFProof_CommittedLogsAgree ----
EXTENDS CCFProof_CommittedLogsAgreeDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM CommittedLogsAgree == Spec => []LogInv
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
