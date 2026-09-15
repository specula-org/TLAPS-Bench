-------------------------------- MODULE Util --------------------------------
EXTENDS Sequences, Functions, Naturals, FiniteSets

max(s) == CHOOSE i \in s : (~\E j \in s : j > i)

ReduceSet(op(_, _), set, base) ==
  LET iter[s \in SUBSET set] ==
        IF s = {} THEN base
        ELSE LET x == CHOOSE x \in s: TRUE
             IN  op(x, iter[s \ {x}])
  IN  iter[set]

ReduceSeq(op(_, _), seq, acc) == FoldFunction(op, acc, seq)

Index(seq, e) ==  CHOOSE i \in 1..Len(seq): seq[i] = e

SeqToSet(s) == {s[i] : i \in DOMAIN s}

INTERSECTION(setOfSets) == ReduceSet(\intersect, setOfSets, UNION setOfSets)

PermSeqs(S) ==
  LET perms[ss \in SUBSET S] ==
       IF ss = {} THEN { << >> }
       ELSE LET ps == [ x \in ss |-> 
                        { Append(sq,x) : sq \in perms[ss \ {x}] } ]
            IN  UNION { ps[x] : x \in ss }
  IN  perms[S]

=============================================================================

