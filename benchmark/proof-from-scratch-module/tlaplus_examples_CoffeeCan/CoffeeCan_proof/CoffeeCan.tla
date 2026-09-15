---------------------------- MODULE CoffeeCan -------------------------------

EXTENDS Naturals

CONSTANT MaxBeanCount

ASSUME MaxBeanFact == MaxBeanCount \in Nat /\ MaxBeanCount >= 1

VARIABLES can

Can == [black : 0..MaxBeanCount, white : 0..MaxBeanCount]

TypeInvariant == can \in Can

Init == can \in {c \in Can : c.black + c.white \in 1..MaxBeanCount}

BeanCount == can.black + can.white

PickSameColorBlack ==
    /\ BeanCount > 1
    /\ can.black >= 2
    /\ can' = [can EXCEPT !.black = @ - 1]

PickSameColorWhite ==
    /\ BeanCount > 1
    /\ can.white >= 2
    /\ can' = [can EXCEPT !.black = @ + 1, !.white = @ - 2]

PickDifferentColor ==
    /\ BeanCount > 1
    /\ can.black >= 1
    /\ can.white >= 1
    /\ can' = [can EXCEPT !.black = @ - 1]

Termination ==
    /\ BeanCount = 1
    /\ UNCHANGED can

Next ==
    \/ PickSameColorWhite
    \/ PickSameColorBlack
    \/ PickDifferentColor
    \/ Termination

Spec ==
    /\ Init
    /\ [][Next]_can
    /\ WF_can(Next)

=============================================================================

