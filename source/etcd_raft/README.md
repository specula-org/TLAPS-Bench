# etcd Raft benchmark model

The model is derived from the etcd Raft example distributed with Specula. Its eight safety theorem statements and task IDs are preserved. `MoreUpToDateCorrectInv` and `LeaderCompletenessInv` are corrected below; `CommitLiveness` adds a ninth target.

The local constant-domain and pending-message repairs remain in place. The crash-recovery repair stores `logEntries` alongside the existing numeric `durableState[i].log` field in `InitDurableState` and `PersistState`. `Restart` restores the saved entries directly.

Previously, recovery took a prefix of the current volatile log using the last persisted length. A reachable conflicting append can truncate or replace those volatile entries before `Ready`. A subsequent crash could therefore either evaluate `SubSeq` beyond its domain or restore different entries of the same length. Keeping a copy of the persisted entries models the intended stable-storage boundary. This does not disable crashes, add assumptions, or weaken any target property.

Implementation reference: `etcd-io/raft` at `3cbf6a74be3fa392edd8b64253fcd11c3ce5649b`. `raftLog.storage` and `raftLog.unstable` hold stable and volatile entries separately; `newLogWithSize` reconstructs the log from storage, while `append` updates the unstable portion. See [log.go](https://github.com/etcd-io/raft/blob/3cbf6a74be3fa392edd8b64253fcd11c3ce5649b/log.go) and the [persistence contract](https://github.com/etcd-io/raft/blob/3cbf6a74be3fa392edd8b64253fcd11c3ce5649b/README.md).

`tests/fixtures/etcd_raft/DurableLogRecovery.tla` follows real model actions through an election, persistence, a conflicting newer-term append, and a restart. Three cases check recovery after truncation, after an unpersisted same-length replacement, and after persisting the replacement. Each trace also checks all eight benchmark safety predicates and its transition relation against the original `Next` relation. These regression traces validate the repair; they are not proofs of all eight unbounded theorems.

## Leader completeness

An entry created in term 1 can remain uncommitted until term 3. A disconnected
term-2 leader need not contain that entry. The previous predicate compared each
current leader's term with the entry's creation term and incorrectly rejected
this legal execution. Raft's [Leader Completeness property](https://raft.github.io/raft.pdf)
(Figure 3 and sections 5.4.2-5.4.3) instead concerns entries committed in an
earlier term.

`commitHistory` records the current term and full log prefix whenever a server's
commit index advances, including when a follower learns a committed prefix.
`electionHistory` records each leader's term and log at election time. The
corrected predicate requires every later-term election to contain each earlier
committed prefix. Both histories survive restart. They are passive observers:
`ProtocolInit`, `ProtocolNext` and the protocol actions preserve the previous
state-machine behavior and assumptions; `Init` and `Next` add history updates.
`NextAsyncCrash` and `NextDynamic` also update the observers.

`tests/fixtures/etcd_raft/LeaderCompleteness.tla` replays the late commit, elects
a term-4 leader, and restarts servers. The creation-term predicate fails on the
same execution; the corrected predicate holds, with its later-election condition
actually exercised. A fault control removes vote log-freshness checking and is
rejected when an incomplete log wins the later election. These finite
regressions do not constitute an unbounded proof. Frozen experiments using the
old context retain their original results and must be distinguished from runs
against the corrected model.

## Quorum log freshness

A single voter can have a committed old-term prefix while a disconnected server
has a conflicting, uncommitted entry with a larger last term. The original
pointwise freshness predicate incorrectly rejected this legal execution.
`MoreUpToDateCorrectInv` now requires freshness relative to an entire quorum
before concluding that a log contains every committed prefix. Raft requires
quorum votes, not one vote, to elect a leader (Raft sections 5.4.1–5.4.3).

`LogFreshness.tla` in `tests/fixtures/etcd_raft` replays a five-server, 70-step
late-commit execution under `Spec`. The old predicate fails; the corrected
predicate holds. A control that disables vote freshness and elects an
incomplete leader is rejected by the corrected predicate.

## Stable-period commit progress

`CommitLiveness` concerns replication after a stable period begins; it does not
prove leader election or unconditional availability. Its parameters range over
a leader, a quorum and an arbitrary positive log index. The environment eventually
stops election timeouts, keeps that leader in the same term, and stops crashes
and RPC loss within the quorum; minority failures remain allowed. Persistence,
retries and commitment are weakly fair. Processing relevant replication requests
and successful acknowledgments is strongly fair, so an enabled RPC class cannot
be perpetually starved by other traffic.

Under those conditions, after finite disruption, a current-term entry at that
index eventually becomes committed. These are explicit scheduling and failure
assumptions, not an assumption that commitment occurs. `Spec` and the eight
safety targets retain their original failure model; `ReplicationNext` only
factors existing actions out of `NextAsync`.

The progress fixture explores finite interleavings from a real election with
two uncommitted entries. A separate fair witness checks that the assumptions
are satisfiable. Removing commit fairness or replacing commitment with a no-op
produces a liveness counterexample. These checks are finite regressions, not an
unbounded TLAPS proof. Old eight-target results retain their original version;
new nine-target runs start with fresh sessions and separate result directories.
