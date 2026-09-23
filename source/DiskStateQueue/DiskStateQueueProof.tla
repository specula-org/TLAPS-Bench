------------------------ MODULE DiskStateQueueProof ------------------------
EXTENDS DiskStateQueueWorkload

THEOREM DeadlockFreedom == Spec => []DeadlockFree
PROOF OMITTED

=============================================================================
