---------------------- MODULE TwoPhaseDefs -----------------------

EXTENDS TwoPhaseModel

vBar == (p + c) % 2

A == INSTANCE Alternate WITH v <- vBar

==============================================================

