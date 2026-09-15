--------------------------- MODULE Disruptor_MPMCDefs --------------------------

EXTENDS Disruptor_MPMCModel

NoDataRaces == Buffer!NoDataRaces

TypeOk ==
  /\ Buffer!TypeOk
  /\ next_sequence    \in Nat
  /\ claimed_sequence \in [ Writers                -> Int                 ]
  /\ published        \in [ 0..Buffer!LastIndex    -> { TRUE, FALSE }     ]
  /\ read             \in [ Readers                -> Int                 ]
  /\ consumed         \in [ Readers                -> Seq(Nat)            ]
  /\ pc               \in [ Writers \union Readers -> { Access, Advance } ]

=============================================================================
