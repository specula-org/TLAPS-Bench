--------------------- MODULE BlockingQueueSplit_proofsDefs ----------------------
EXTENDS BlockingQueueSplit, TLAPS

IInv ==
    /\ Len(buffer) \in 0..BufCapacity
    /\ waitSetP \in SUBSET Producers
    /\ waitSetC \in SUBSET Consumers
    /\ (waitSetC \cup waitSetP) # (Producers \cup Consumers)
    /\ buffer = <<>> => \E p \in Producers : p \notin (waitSetC \cup waitSetP)
    /\ Len(buffer) = BufCapacity => \E c \in Consumers : c \notin (waitSetC \cup waitSetP)

=============================================================================
