
-------------------------- MODULE AlphaConstants ----------------------------

EXTENDS AlphaInterface, Sequences

-----------------------------------------------------------------------------
AllOnes == [n \in 0..(DataLen - 1) |-> 1]

NotChosen == CHOOSE nc : nc \notin Data
Failed    == CHOOSE f  : f  \notin Data \cup {NotChosen}

NoSource    == CHOOSE ns : ns \notin [proc : Proc, idx : Nat]
FromInitMem == CHOOSE fm : fm \notin [proc : Proc, idx : Nat] \cup {NoSource}

MaskVal(old, mask, new) ==

  [i \in 0..(DataLen-1) |-> IF mask[i]=1 THEN new[i] ELSE old[i]]

=============================================================================
