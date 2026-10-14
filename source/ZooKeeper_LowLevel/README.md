# ZooKeeper 3.7 synchronization model

The nine safety targets are unchanged. This revision repairs synchronization
and recovery behavior exposed by a reachable incomplete-SNAP execution.

ZooKeeper 3.7.0's `Learner.shutdown` requests a full database shutdown while
SNAP synchronization is incomplete. `ZooKeeperServer.shutdown(true)` clears
the temporary database so the next load uses persistent history. The model
retains the pre-SNAP history and commit position in `connectInfo.backup` and
restores them when that synchronization is interrupted, including a leader
shutdown affecting its learners. A completed NEWLEADER handshake clears SNAP
mode and retains the synchronized history.

`Learner.syncWithLeader` invokes `truncateLog` without comparing its target with
a provisional in-memory commit index. A failed truncation exits the process;
the model now takes the existing crash transition instead of discarding TRUNC
and continuing to acknowledge NEWLEADER. Taking a replacement snapshot updates
its position even if the replacement history is shorter.

Implementation references, pinned to release 3.7.0:
[Learner.java](https://github.com/apache/zookeeper/blob/release-3.7.0/zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java),
[ZooKeeperServer.java](https://github.com/apache/zookeeper/blob/release-3.7.0/zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java),
[ZKDatabase.java](https://github.com/apache/zookeeper/blob/release-3.7.0/zookeeper-server/src/main/java/org/apache/zookeeper/server/ZKDatabase.java).

`tests/fixtures/zookeeper_sync/SnapshotRecovery.tla` follows 124 original
transitions from `Init` to an unfinished SNAP. It then exercises leader failure,
follower failure, partition and completion before failure, checking `Spec`,
all nine safety predicates, types and commit-index bounds. Disabling recovery
reproduces the retained-temporary-history defect. These finite regressions do
not establish unbounded safety or complete disk-format fidelity. Proof runs
using the previous model remain historical results and must not be overwritten.
