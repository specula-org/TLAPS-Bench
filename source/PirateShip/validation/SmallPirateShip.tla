---- MODULE SmallPirateShip ----
EXTENDS PirateShipProof
CONSTANT MaxView, MaxBranch, MaxChannel
Small ==
    /\ \A r \in R: view[r] <= MaxView /\ Len(branch[r]) <= MaxBranch
    /\ \A r, s \in R: Len(network[r][s]) <= MaxChannel
====
