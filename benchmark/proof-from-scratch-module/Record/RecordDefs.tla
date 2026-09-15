------------------------------- MODULE RecordDefs -------------------------------

EXTENDS RecordModel

maxBal == [p \in Participant |-> state[p][p].maxBal]

SV == INSTANCE SimpleVoting

=============================================================================

