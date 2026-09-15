---- MODULE SequencesTheorems ----
EXTENDS SequencesTheoremsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM RemoveSeq ==
   ASSUME NEW S, NEW seq \in Seq(S),
          NEW i \in 1..Len(seq)
   PROVE   Remove(i, seq) \in Seq(S)
\* BEGIN AGENT PROOF Data/SequencesTheorems_RemoveSeq.tla
PROOF OMITTED
\* END AGENT PROOF Data/SequencesTheorems_RemoveSeq.tla
====
