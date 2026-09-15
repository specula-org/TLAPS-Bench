-------------------------------- MODULE Nano_SafetyDefs --------------------------------

EXTENDS NanoModel

Ledger == [Hash -> SignedBlock \cup {NoBlock}]

TypeInvariant ==
    /\ lastHash \in Hash \cup {NoHash}
    /\ distributedLedger \in [Node -> Ledger]
    /\ received \in [Node -> SUBSET SignedBlock]

CryptographicInvariant ==
    /\ \A node \in Node :
        LET ledger == distributedLedger[node] IN
        /\ \A hash \in Hash :
            LET signedBlock == ledger[hash] IN
            /\ signedBlock /= NoBlock =>
                LET publicKey == PublicKeyOf(ledger, hash) IN
                /\ ValidateSignature(
                    signedBlock.signature,
                    publicKey,
                    hash)

SafetyInvariant ==
    /\ CryptographicInvariant

=============================================================================

