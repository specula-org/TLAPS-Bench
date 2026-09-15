----------------------------- MODULE Disruptor_SPMC_TypeOkCorrectDefs ------------------------

EXTENDS Disruptor_SPMCModel

TypeOk ==
  /\ Buffer!TypeOk
  /\ published \in Int
  /\ read      \in [ Readers                -> Int                 ]
  /\ consumed  \in [ Readers                -> Seq(Nat)            ]
  /\ pc        \in [ Writers \union Readers -> { Access, Advance } ]

=============================================================================
