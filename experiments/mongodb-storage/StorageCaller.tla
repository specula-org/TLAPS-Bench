--------------------------- MODULE StorageCaller ---------------------------
EXTENDS StorageTimestamps

\* Explicit caller contract motivated by MultiShardTxn's NextTs prepare call.
\* Existing prepared commits may still append behind newer commits.
FreshPrepareCall ==
  \A n \in Node, t \in MTxId, ts \in Timestamps :
    PrepareTransaction(n,t,ts) => \A i \in DOMAIN mlog[n] : mlog[n][i].ts < ts

CallerEpochNext == EpochNext /\ FreshPrepareCall
CallerEpochSpec == Init /\ [][CallerEpochNext]_vars

THEOREM CallerEpochProjection == CallerEpochSpec => EpochSpec
BY PTL DEF CallerEpochSpec, CallerEpochNext, EpochSpec

THEOREM LogTimestampSetsAgree ==
  ASSUME NEW n \in Node, TimestampShape
  PROVE PrepareOrCommitTimestamps(n) = CommitTimestamps(n)
BY SMT DEF TimestampShape, PrepareOrCommitTimestamps, CommitTimestamps, Range

THEOREM NextTsIsNewerThanLog ==
  ASSUME NEW n \in Node, Inv, TimestampShape, TimestampBound
  PROVE \A i \in DOMAIN mlog[n] : mlog[n][i].ts < NextTs(n)
<1>1. PICK b \in Nat : (ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \subseteq 0..b
  BY SMT DEF TimestampBound
<1>2. PrepareOrCommitTimestamps(n) = CommitTimestamps(n)
  BY SMT, LogTimestampSetsAgree
<1>3. ASSUME NEW i \in DOMAIN mlog[n]
      PROVE mlog[n][i].ts < NextTs(n)
  <2>1. mlog[n][i].ts \in ActiveReadTimestamps(n) \cup CommitTimestamps(n)
    BY SMT, <1>3 DEF CommitTimestamps
  <2>2. /\ Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \in 0..b
          /\ mlog[n][i].ts <= Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n))
    BY SMT, <1>1, <2>1, BoundedMaximum
  <2> QED BY SMT, <1>1, <1>2, <2>1, <2>2 DEF NextTs
<1> QED BY SMT, <1>3
=============================================================================
