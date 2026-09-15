------------------------------ MODULE Alternate -----------------------------

EXTENDS Naturals
VARIABLE v, x
CONSTANT XInit(_), XAct(_, _, _)

Init == v = 0 /\ XInit(x)
Next == v' = (v + 1) % 2 /\ XAct(v, x, x')

Spec == Init /\ [][Next]_<<v,x>>

============================================================================

