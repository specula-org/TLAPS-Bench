---- MODULE RecursionProof ----
EXTENDS PirateShip
LOCAL NI == INSTANCE NaturalsInduction
LOCAL TL == INSTANCE TLAPS

THEOREM QuorumScanUnfold ==
    ASSUME NEW Q, NEW b, NEW m, NEW default \in Nat, Len(b) \in Nat
    PROVE QuorumScan(Q, b, m, default) =
        [i \in default..Len(b) |->
            IF i = default THEN default
            ELSE IF \E q \in Q: \A n \in q: m[n] >= i
                 THEN i ELSE QuorumScan(Q, b, m, default)[i-1]]
<1> DEFINE Step(previous, i) ==
               IF \E q \in Q: \A n \in q: m[n] >= i THEN i ELSE previous
           f == QuorumScan(Q, b, m, default)
<1>1. NI!FiniteNatInductiveDefHypothesis(f, default, Step, default, Len(b))
    BY DEF NI!FiniteNatInductiveDefHypothesis, f, QuorumScan, Step
<1>2. NI!FiniteNatInductiveDefConclusion(f, default, Step, default, Len(b))
    BY <1>1, NI!FiniteNatInductiveDef
<1> QED
    BY <1>2 DEF NI!FiniteNatInductiveDefConclusion, f, Step

THEOREM UnanimityScanUnfold ==
    ASSUME NEW b, NEW idx, NEW r, Len(b) \in Nat
    PROVE LET V(S, i) == S \cup b[i].auditQCVotes \cup IF i <= idx THEN {r} ELSE {}
          IN UnanimityScan(b, idx, r) =
            [i \in 0..Len(b) |->
                IF i = 0 THEN [S \in SUBSET R |-> {0}]
                ELSE [S \in SUBSET R |->
                    IF V(S, i) = R THEN b[i].auditQC
                    ELSE UnanimityScan(b, idx, r)[i-1][V(S, i)]]]
<1> DEFINE V(S, i) == S \cup b[i].auditQCVotes \cup IF i <= idx THEN {r} ELSE {}
           Step(previous, i) ==
               [S \in SUBSET R |-> IF V(S, i) = R THEN b[i].auditQC ELSE previous[V(S, i)]]
           base == [S \in SUBSET R |-> {0}]
           f == UnanimityScan(b, idx, r)
<1>1. NI!FiniteNatInductiveDefHypothesis(f, base, Step, 0, Len(b))
    BY DEF NI!FiniteNatInductiveDefHypothesis, f, base, UnanimityScan, Step, V
<1>2. NI!FiniteNatInductiveDefConclusion(f, base, Step, 0, Len(b))
    BY <1>1, NI!FiniteNatInductiveDef
<1> QED
    BY <1>2 DEF NI!FiniteNatInductiveDefConclusion, f, base, Step, V

THEOREM QuorumScanBoundary ==
    ASSUME NEW Q, NEW b, NEW m, Len(b) \in Nat
    PROVE MaxQuorum(Q, b, m, Len(b)) = Len(b)
BY QuorumScanUnfold, TL!SMT DEF MaxQuorum

THEOREM UnanimityScanBoundary ==
    ASSUME NEW b, NEW idx, NEW r, Len(b) \in Nat
    PROVE UnanimityScan(b, idx, r)[0][{}] = {0}
BY UnanimityScanUnfold, TL!SMT

THEOREM UnanimityDomainClosed ==
    ASSUME NEW S \in SUBSET R, NEW votes \in SUBSET R,
           NEW r \in R, NEW i \in Nat, NEW idx \in Nat
    PROVE S \cup votes \cup (IF i <= idx THEN {r} ELSE {}) \in SUBSET R
BY TL!SMT

====
