-------------------------------- MODULE LockHSModel --------------------------------

EXTENDS Lock, NaturalsInduction

VARIABLE h_turn
NoHistoryChange(A) == A /\ UNCHANGED h_turn

VARIABLE s
INSTANCE Stuttering

Other(p) == IF p = 1 THEN 2 ELSE 1 

InitHS == Init /\ (h_turn = 1) /\ (s = top)

l1HS(self) == 
  /\ PostStutter(l1(self), "l1", self, 1, 2, LAMBDA j : j-1)
  /\ h_turn' = IF s' # top THEN IF s'.val = 1 THEN Other(self)
                                              ELSE h_turn
                           ELSE h_turn

procHS(self) == 
  \/ NoStutter(NoHistoryChange(l0(self)))
  \/ l1HS(self)
  \/ NoStutter(NoHistoryChange(cs(self)))
  \/ NoStutter(NoHistoryChange(l2(self)))

NextHS == (\E self \in 1..2: procHS(self))

SpecHS == InitHS /\ [][NextHS]_<<vars, h_turn, s>>

===============================================================================
