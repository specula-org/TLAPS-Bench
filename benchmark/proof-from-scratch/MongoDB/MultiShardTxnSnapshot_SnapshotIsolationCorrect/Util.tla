-------------------------------- MODULE Util --------------------------------
EXTENDS Sequences, Functions, Naturals, FiniteSets

max(s) == CHOOSE i \in s : (~\E j \in s : j > i)

PermSeqs(S) ==
  LET perms[ss \in SUBSET S] ==
       IF ss = {} THEN { << >> }
       ELSE UNION {{Append(sq, x) : sq \in perms[ss \ {x}]} : x \in ss}
  IN  perms[S]

=============================================================================

