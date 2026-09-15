----------------------------- MODULE stages -----------------------------

EXTENDS Naturals 

CONSTANTS DNA, PRIMER 

VARIABLES tee, 
          primer, 
          dna, 
          template, 
          hybrid, 
          stage, 
          cycle 

vars == << tee, primer, dna, template, hybrid, stage, cycle >>

natMin(i,j) == IF i < j THEN i ELSE j 

heat ==    /\ tee = "Hot" 
           /\ tee' = "TooHot" 
           /\ primer' = primer + hybrid 
           /\ dna' = 0 
           /\ template' = template + hybrid + 2 * dna 
           /\ hybrid' = 0 
           /\ (stage = "init" \/ stage = "extended")
           /\ stage' = "denatured"
           /\ UNCHANGED cycle

cool ==   /\ tee = "TooHot" 
          /\ tee' = "Hot" 
          /\ UNCHANGED << cycle, primer, dna, template, hybrid >>
          /\ stage = "denatured"
          /\ stage' = "ready"

anneal ==   /\ tee = "Hot" 
            /\ tee' = "Warm" 
            /\ UNCHANGED <<cycle, dna>> 
            
            /\ \E k \in 1..natMin(primer, template) : 
                /\ primer' = primer - k 
                /\ template' = template - k 
                /\ hybrid' = hybrid + k 
            /\ stage = "ready"
            /\ stage' = "annealed"
            
extend ==   /\ tee = "Warm" 
            /\ tee' = "Hot" 
            /\ UNCHANGED <<primer, template>>
            /\ dna' = dna + hybrid 
            /\ hybrid' = 0 
            /\ stage = "annealed"
            /\ stage' = "extended"
            /\ cycle' = cycle + 1 

Init == /\ tee = "Hot" 
        /\ primer = PRIMER 
        /\ dna = DNA 
        /\ template = 0 
        /\ hybrid = 0 
        /\ stage = "init"
        /\ cycle = 0 

Next == \/ heat
        \/ cool
        \/ anneal
        \/ extend

Spec == /\ Init 
        /\ [][Next]_vars 
        /\ WF_vars(anneal) 
        /\ WF_vars(heat)
        /\ WF_vars(cool)
        /\ WF_vars(extend)

TypeOK == 
    /\ tee \in {"Warm", "Hot", "TooHot"}
    /\ primer \in Nat
    /\ dna \in Nat
    /\ template \in Nat
    /\ hybrid \in Nat
    /\ stage \in {"init","ready","annealed","extended","denatured"}
    /\ cycle \in Nat

cleanInstance == INSTANCE clean

=============================================================================
