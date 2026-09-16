---------------------- MODULE StorageCoherenceInduction ----------------------
EXTENDS StorageCoherenceAttempt
CONSTANT N, Writer, Reader, K

\* Deliberately synthetic, NOT Storage.Init and NOT claimed reachable.
\* It meets every premise used in PreparedCommitCoherenceAttempt but lacks
\* the crucial provenance link from a prepared snapshot to its prepare log.
WitnessInit ==
  /\ mlog = [n \in Node |-> <<>>]
  /\ mcommitIndex = [n \in Node |-> 0]
  /\ txnStatus = [n \in Node |-> [t \in MTxId |-> STATUS_OK]]
  /\ stableTs = [n \in Node |-> -1]
  /\ oldestTs = [n \in Node |-> -1]
  /\ allDurableTs = [n \in Node |-> 0]
  /\ mtxnSnapshots = [n \in Node |-> [t \in MTxId |->
       [active |-> TRUE, committed |-> FALSE, aborted |-> FALSE,
        ts |-> IF t = Writer THEN 0 ELSE 1,
        prepared |-> t = Writer,
        prepareTs |-> IF t = Writer THEN 1 ELSE 0,
        ignorePrepare |-> "false", readSet |-> {},
        writeSet |-> IF t = Writer THEN {K} ELSE {},
        data |-> [k \in Keys |-> IF t = Writer /\ k = K THEN Writer ELSE NoValue]]]]
  /\ Inv /\ Lifecycle /\ PrepareModeInvariant /\ ExternalCoherence

WitnessNext == CommitPreparedTransaction(N,Writer,1,1)
=============================================================================
