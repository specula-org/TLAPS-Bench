-------------------------- MODULE StorageSeqLemmas --------------------------
EXTENDS Storage, TLAPS

IsSeq(s) == s \in Seq(Range(s))

THEOREM EmptyIsSeq == IsSeq(<<>>)
BY SMT DEF IsSeq, Range

THEOREM SequenceDomain ==
  ASSUME NEW s, IsSeq(s)
  PROVE /\ Len(s) \in Nat
        /\ DOMAIN s = 1..Len(s)
BY SMT DEF IsSeq

THEOREM AppendEntries ==
  ASSUME NEW s, NEW e, IsSeq(s)
  PROVE /\ Len(Append(s,e)) = Len(s)+1
        /\ DOMAIN Append(s,e) = 1..(Len(s)+1)
        /\ \A i \in DOMAIN s : Append(s,e)[i] = s[i]
        /\ Append(s,e)[Len(s)+1] = e
BY Isa DEF IsSeq

THEOREM AppendRange ==
  ASSUME NEW s, NEW e, IsSeq(s)
  PROVE Range(Append(s,e)) = Range(s) \cup {e}
BY SMT, AppendEntries, SequenceDomain DEF IsSeq, Range

THEOREM AppendIsSeq ==
  ASSUME NEW s, NEW e, IsSeq(s)
  PROVE IsSeq(Append(s,e))
BY SMT, AppendRange, SequenceDomain DEF IsSeq, Range, Append, \o

=============================================================================
