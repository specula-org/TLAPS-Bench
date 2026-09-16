------------------------- MODULE StorageLogAlgebra -------------------------
EXTENDS StorageSeqLemmas

DurableEntry(n,t,ts,dts) ==
  [data |-> [k \in SnapshotUpdatedKeys(n,t) |-> mtxnSnapshots[n][t].data[k]],
   ts |-> ts, tid |-> t, durableTs |-> dts]

THEOREM DurableAppendForm ==
  ASSUME NEW n, NEW t, NEW ts, NEW dts
  PROVE CommitTxnToLogWithDurable(n,t,ts,dts) = Append(mlog[n],DurableEntry(n,t,ts,dts))
BY Isa DEF CommitTxnToLogWithDurable, CommitLogEntry, DurableEntry

THEOREM AppendImage ==
  ASSUME NEW s, NEW e, NEW F(_), IsSeq(s)
  PROVE {F(Append(s,e)[i]) : i \in DOMAIN Append(s,e)} =
          {F(s[i]) : i \in DOMAIN s} \cup {F(e)}
BY SMT, AppendEntries, SequenceDomain
=============================================================================
