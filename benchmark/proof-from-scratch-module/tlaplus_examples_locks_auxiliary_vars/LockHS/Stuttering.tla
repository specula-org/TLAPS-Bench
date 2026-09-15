----------------------------- MODULE Stuttering ----------------------------

EXTENDS Naturals, TLC
top == [top |-> "top"] 

VARIABLES s, vars

NoStutter(A) == (s = top) /\ A /\ (s' = s)

PostStutter(A, actionId, context, bot, initVal, decr(_)) ==
  IF s = top THEN /\ A 
                  /\ s' = [id |-> actionId, ctxt |-> context, val |-> initVal]
             ELSE /\ s.id = actionId
                  /\ s.ctxt = context 
                  /\ UNCHANGED vars 
                  /\ s'= IF s.val = bot THEN top 
                                        ELSE [s EXCEPT !.val = decr(s.val)]

-----------------------------------------------------------------------------

StutterConstantCondition(Sigma, bot, decr(_)) ==
  LET InverseDecr(S) == {sig \in Sigma \ S : decr(sig) \in S}
      R[n \in Nat] == IF n = 0 THEN {bot}
                               ELSE LET T == R[n-1] 
                                    IN  T \cup InverseDecr(T)
                        
  IN Sigma = UNION {R[n] : n \in Nat}

=============================================================================

