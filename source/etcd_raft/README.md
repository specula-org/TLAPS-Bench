# etcd Raft benchmark model

The model is derived from the etcd Raft example distributed with Specula. Its eight selected safety theorem statements are preserved.

The local constant-domain and pending-message repairs remain in place. The crash-recovery repair stores `logEntries` alongside the existing numeric `durableState[i].log` field in `InitDurableState` and `PersistState`. `Restart` restores the saved entries directly.

Previously, recovery took a prefix of the current volatile log using the last persisted length. A reachable conflicting append can truncate or replace those volatile entries before `Ready`. A subsequent crash could therefore either evaluate `SubSeq` beyond its domain or restore different entries of the same length. Keeping a copy of the persisted entries models the intended stable-storage boundary. This does not disable crashes, add assumptions, or weaken any target property.

Implementation reference: `etcd-io/raft` at `3cbf6a74be3fa392edd8b64253fcd11c3ce5649b`. `raftLog.storage` and `raftLog.unstable` hold stable and volatile entries separately; `newLogWithSize` reconstructs the log from storage, while `append` updates the unstable portion. See [log.go](https://github.com/etcd-io/raft/blob/3cbf6a74be3fa392edd8b64253fcd11c3ce5649b/log.go) and the [persistence contract](https://github.com/etcd-io/raft/blob/3cbf6a74be3fa392edd8b64253fcd11c3ce5649b/README.md).

`tests/fixtures/etcd_raft/DurableLogRecovery.tla` follows real model actions through an election, persistence, a conflicting newer-term append, and a restart. Three cases check recovery after truncation, after an unpersisted same-length replacement, and after persisting the replacement. Each trace also checks all eight benchmark safety predicates and its transition relation against the original `Next` relation. These regression traces validate the repair; they are not proofs of all eight unbounded theorems.
