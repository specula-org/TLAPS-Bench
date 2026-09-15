---- MODULE VoteProof ----
EXTENDS VoteProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM VInv3 => VInv1
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_VInv1.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_VInv1.tla

THEOREM VT2 == Spec => []VInv
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_VT2.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_VT2.tla

THEOREM VT3 == Spec => C!Spec
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_VT3.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_VT3.tla

THEOREM Liveness == LiveSpec => C!LiveSpec
\* BEGIN AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_byzpaxos/VoteProof_Liveness.tla
====
