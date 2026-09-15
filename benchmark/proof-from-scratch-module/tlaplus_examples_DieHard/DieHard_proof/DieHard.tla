------------------------------ MODULE DieHard ------------------------------- 

EXTENDS Naturals

VARIABLES big,   
          small  

TypeOK == /\ small \in 0..3 
          /\ big   \in 0..5

Init == /\ big = 0 
        /\ small = 0

FillSmallJug  == /\ small' = 3 
                 /\ big' = big

FillBigJug    == /\ big' = 5 
                 /\ small' = small

EmptySmallJug == /\ small' = 0 
                 /\ big' = big

EmptyBigJug   == /\ big' = 0 
                 /\ small' = small

Min(m,n) == IF m < n THEN m ELSE n

SmallToBig == /\ big'   = Min(big + small, 5)
              /\ small' = small - (big' - big)

BigToSmall == /\ small' = Min(big + small, 3) 
              /\ big'   = big - (small' - small)

Next ==  \/ FillSmallJug 
         \/ FillBigJug    
         \/ EmptySmallJug 
         \/ EmptyBigJug    
         \/ SmallToBig    
         \/ BigToSmall    

Spec == Init /\ [][Next]_<<big, small>> 
-----------------------------------------------------------------------------

=============================================================================
