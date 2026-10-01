---- MODULE PirateShipProof_CommittedBranchAppendOnlyPropCorrect ----
EXTENDS PirateShipProof_CommittedBranchAppendOnlyPropCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM CommittedBranchAppendOnlyPropCorrect == Spec => CommittedBranchAppendOnlyProp
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====
