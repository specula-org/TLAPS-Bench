----------------------------- MODULE SimpleMutexDefs -----------------------------
EXTENDS SimpleMutexModel

TypeOK ==
  /\ trying \in [{0,1} -> BOOLEAN]
  /\ pc \in [{0,1} -> {"a", "b", "cs", "Done"}]

Inv == \A i \in {0,1} :
          /\ pc[i] \in {"b", "cs"} => trying[i]
          /\ pc[i] = "cs" => pc[1-i] # "cs"

MutualExclusion == ~(pc[0] = "cs" /\ pc[1] = "cs")

=============================================================================
