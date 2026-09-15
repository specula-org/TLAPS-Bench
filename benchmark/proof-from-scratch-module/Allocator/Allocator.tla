---- MODULE Allocator ----
EXTENDS AllocatorDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM InitTypeInvariant == Init => TypeInvariant
\* BEGIN AGENT PROOF Allocator/Allocator_InitTypeInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Allocator/Allocator_InitTypeInvariant.tla

THEOREM NextTypeInvariant == TypeInvariant /\ Next => TypeInvariant'
\* BEGIN AGENT PROOF Allocator/Allocator_NextTypeInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Allocator/Allocator_NextTypeInvariant.tla

THEOREM InitMutex == Init => Mutex
\* BEGIN AGENT PROOF Allocator/Allocator_InitMutex.tla
PROOF OMITTED
\* END AGENT PROOF Allocator/Allocator_InitMutex.tla

THEOREM NextMutex == TypeInvariant /\ Mutex /\ Next => Mutex'
\* BEGIN AGENT PROOF Allocator/Allocator_NextMutex.tla
PROOF OMITTED
\* END AGENT PROOF Allocator/Allocator_NextMutex.tla
====
