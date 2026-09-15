--------------------- MODULE AllocatorImplementation_proofDefs -----------------

EXTENDS AllocatorImplementation, Integers, SequenceTheorems,
        FiniteSets, FiniteSetTheorems, WellFoundedInduction, TLAPS

ASSUME ClientsFinite == IsFiniteSet(Clients)

============================================================================
