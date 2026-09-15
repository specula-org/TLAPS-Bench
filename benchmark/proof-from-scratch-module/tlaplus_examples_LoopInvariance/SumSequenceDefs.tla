---------------------------- MODULE SumSequenceDefs ----------------------------

EXTENDS SumSequenceModel

SeqSum(s) == 
  LET SS[ss \in Seq(Int)] == IF ss = << >> THEN 0 ELSE ss[1] + SS[Tail(ss)]
  IN  SS[s]

PCorrect == (pc = "Done") => (sum = SeqSum(seq))

=============================================================================

