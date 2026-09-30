---- MODULE PirateShipProof ----
EXTENDS PirateShipProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOKCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_TypeOKCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_TypeOKCorrect.tla

THEOREM IndexBoundsInvCorrect == Spec => []IndexBoundsInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_IndexBoundsInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_IndexBoundsInvCorrect.tla

THEOREM BranchInvCorrect == Spec => []BranchInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_BranchInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_BranchInvCorrect.tla

THEOREM AuditBranchInvCorrect == Spec => []AuditBranchInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_AuditBranchInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_AuditBranchInvCorrect.tla

THEOREM OneLeaderPerViewInvCorrect == Spec => []OneLeaderPerViewInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_OneLeaderPerViewInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_OneLeaderPerViewInvCorrect.tla

THEOREM WellFormedBranchInvCorrect == Spec => []WellFormedBranchInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_WellFormedBranchInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_WellFormedBranchInvCorrect.tla

THEOREM ViewMonotonicInvCorrect == Spec => []ViewMonotonicInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_ViewMonotonicInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_ViewMonotonicInvCorrect.tla

THEOREM ViewStabilizationInvCorrect == Spec => []ViewStabilizationInv
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_ViewStabilizationInvCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_ViewStabilizationInvCorrect.tla

THEOREM CommittedBranchAppendOnlyPropCorrect == Spec => CommittedBranchAppendOnlyProp
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_CommittedBranchAppendOnlyPropCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_CommittedBranchAppendOnlyPropCorrect.tla

THEOREM AuditedBranchAppendOnlyPropCorrect == Spec => AuditedBranchAppendOnlyProp
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_AuditedBranchAppendOnlyPropCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_AuditedBranchAppendOnlyPropCorrect.tla

THEOREM MonotonicAuditedIndexPropCorrect == Spec => MonotonicAuditedIndexProp
\* BEGIN AGENT PROOF PirateShip/PirateShipProof_MonotonicAuditedIndexPropCorrect.tla
PROOF OMITTED
\* END AGENT PROOF PirateShip/PirateShipProof_MonotonicAuditedIndexPropCorrect.tla
====
