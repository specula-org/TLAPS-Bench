-------------------------------- MODULE NanoModel --------------------------------

EXTENDS
    Naturals,
    Bags

CONSTANTS
    Hash,                   
    CalculateHash(_,_,_),   
    PrivateKey,             
    PublicKey,              
    KeyPair,                
    Node,                   
    GenesisBalance,         
    Ownership               

VARIABLES
    lastHash,               
    distributedLedger,      
    received                

ASSUME ConstantTypes ==
    /\ \A data, oldHash, newHash :
        /\ CalculateHash(data, oldHash, newHash) \in BOOLEAN
    /\ KeyPair \in [PrivateKey -> PublicKey]
    /\ GenesisBalance \in Nat
    /\ Ownership \in [Node -> PrivateKey]

SignHash(hash, privateKey) ==
    [data       |-> hash,
    signedWith  |-> privateKey]

ValidateSignature(signature, expectedPublicKey, expectedHash) ==
    LET publicKey == KeyPair[signature.signedWith] IN
    /\ publicKey = expectedPublicKey
    /\ signature.data = expectedHash

Signature ==
    [data       : Hash,
    signedWith  : PrivateKey]

AccountBalance == 0 .. GenesisBalance

GenesisBlock ==
    [type       : {"genesis"},
    account     : PublicKey,
    balance     : {GenesisBalance}]

SendBlock ==
    [previous   : Hash,
    balance     : AccountBalance,
    destination : PublicKey,
    type        : {"send"}]

OpenBlock ==
    [account    : PublicKey,
    source      : Hash,
    rep         : PublicKey,
    type        : {"open"}]

ReceiveBlock ==
    [previous   : Hash,
    source      : Hash,
    type        : {"receive"}]

ChangeRepBlock ==
    [previous   : Hash,
    rep         : PublicKey,
    type        : {"change"}]

Block ==
    GenesisBlock
    \cup SendBlock
    \cup OpenBlock
    \cup ReceiveBlock
    \cup ChangeRepBlock

SignedBlock ==
    [block      : Block,
    signature   : Signature]

NoBlock == CHOOSE b : b \notin SignedBlock

NoHash == CHOOSE h : h \notin Hash

GenesisBlockExists ==
    /\ lastHash /= NoHash

IsAccountOpen(ledger, publicKey) ==
    /\ \E hash \in Hash :
        LET signedBlock == ledger[hash] IN
        /\ signedBlock /= NoBlock
        /\ signedBlock.block.type \in {"genesis", "open"}
        /\ signedBlock.block.account = publicKey

IsSendReceived(ledger, sourceHash) ==
    /\ \E hash \in Hash :
        LET signedBlock == ledger[hash] IN
        /\ signedBlock /= NoBlock
        /\ signedBlock.block.type \in {"open", "receive"}
        /\ signedBlock.block.source = sourceHash

PublicKeyOf(ledger, blockHash) ==
    LET publicKeyOf[hash \in Hash] ==
          LET block == ledger[hash].block
          IN  IF block.type \in {"genesis", "open"}
              THEN block.account
              ELSE publicKeyOf[block.previous]
    IN  publicKeyOf[blockHash]

BalanceAt(ledger, hash) ==
    LET balanceAt[h \in Hash] ==
          LET block == ledger[h].block
              valueOfSend(sourceHash) ==
                LET sourceBlock == ledger[sourceHash].block
                IN  balanceAt[sourceBlock.previous] - sourceBlock.balance
          IN  CASE block.type = "open" -> valueOfSend(block.source)
              [] block.type = "send" -> block.balance
              [] block.type = "receive" ->
                  balanceAt[block.previous] + valueOfSend(block.source)
              [] block.type = "change" -> balanceAt[block.previous]
              [] block.type = "genesis" -> block.balance
    IN  balanceAt[hash]

CreateGenesisBlock(privateKey) ==
    LET
      publicKey == KeyPair[privateKey]
      genesisBlock ==
        [type   |-> "genesis",
        account |-> publicKey,
        balance |-> GenesisBalance]
    IN
    /\ ~GenesisBlockExists
    /\ CalculateHash(genesisBlock, lastHash, lastHash')
    /\ distributedLedger' =
        LET signedGenesisBlock ==
            [block      |-> genesisBlock,
            signature   |-> SignHash(lastHash', privateKey)]
        IN
        [n \in Node |->
            [distributedLedger[n] EXCEPT
                ![lastHash'] =
                    signedGenesisBlock]]
    /\ UNCHANGED received

ValidateOpenBlock(ledger, block) ==
    /\ block.type = "open"
    /\ ledger[block.source] /= NoBlock
    /\ ledger[block.source].block.type = "send"
    /\ ledger[block.source].block.destination = block.account

CreateOpenBlock(node) ==
    LET
      privateKey == Ownership[node]
      publicKey == KeyPair[privateKey]
      ledger == distributedLedger[node]
    IN
    /\ \E repPublicKey \in PublicKey :
        /\ \E srcHash \in Hash :
            LET newOpenBlock ==
                [account    |-> publicKey,
                source      |-> srcHash,
                rep         |-> repPublicKey,
                type        |-> "open"]
            IN
            /\ ValidateOpenBlock(ledger, newOpenBlock)
            /\ CalculateHash(newOpenBlock, lastHash, lastHash')
            /\ received' =
                LET signedOpenBlock ==
                    [block      |-> newOpenBlock,
                    signature   |-> SignHash(lastHash', privateKey)]
                IN
                [n \in Node |->
                    received[n] \cup {signedOpenBlock}]
            /\ UNCHANGED distributedLedger

ProcessOpenBlock(node, signedBlock) ==
    LET
      ledger == distributedLedger[node]
      block == signedBlock.block
    IN
    /\ ValidateOpenBlock(ledger, block)
    /\ ~IsAccountOpen(ledger, block.account)
    /\ CalculateHash(block, lastHash, lastHash')
    /\ ValidateSignature(signedBlock.signature, block.account, lastHash')
    /\ distributedLedger' =
        [distributedLedger EXCEPT
            ![node][lastHash'] = signedBlock]

ValidateSendBlock(ledger, block) ==
    /\ block.type = "send"
    /\ ledger[block.previous] /= NoBlock
    /\ block.balance <= BalanceAt(ledger, block.previous)

CreateSendBlock(node) ==
    LET
      privateKey == Ownership[node]
      publicKey == KeyPair[privateKey]
      ledger == distributedLedger[node]
    IN
    /\ \E prevHash \in Hash :
        /\ ledger[prevHash] /= NoBlock
        /\ PublicKeyOf(ledger, prevHash) = publicKey
        /\ \E recipient \in PublicKey :
            /\ \E newBalance \in AccountBalance :
                LET newSendBlock ==
                    [previous   |-> prevHash,
                    balance     |-> newBalance,
                    destination |-> recipient,
                    type        |-> "send"]
                IN
                /\ ValidateSendBlock(ledger, newSendBlock)
                /\ CalculateHash(newSendBlock, lastHash, lastHash')
                /\ received' =
                    LET signedSendBlock ==
                        [block      |-> newSendBlock,
                        signature   |-> SignHash(lastHash', privateKey)]
                    IN
                    [n \in Node |->
                        received[n] \cup {signedSendBlock}]
                /\ UNCHANGED distributedLedger

ProcessSendBlock(node, signedBlock) ==
    LET
      ledger == distributedLedger[node]
      block == signedBlock.block
    IN
    /\ ValidateSendBlock(ledger, block)
    /\ CalculateHash(block, lastHash, lastHash')
    /\ ValidateSignature(
        signedBlock.signature,
        PublicKeyOf(ledger, block.previous),
        lastHash')
    /\ distributedLedger' =
        [distributedLedger EXCEPT
            ![node][lastHash'] = signedBlock]

ValidateReceiveBlock(ledger, block) ==
    /\ block.type = "receive"
    /\ ledger[block.previous] /= NoBlock
    /\ ledger[block.source] /= NoBlock
    /\ ledger[block.source].block.type = "send"
    /\ ledger[block.source].block.destination =
        PublicKeyOf(ledger, block.previous)

CreateReceiveBlock(node) ==
    LET
      privateKey == Ownership[node]
      publicKey == KeyPair[privateKey]
      ledger == distributedLedger[node]
    IN
    /\ \E prevHash \in Hash : 
        /\ ledger[prevHash] /= NoBlock
        /\ PublicKeyOf(ledger, prevHash) = publicKey
        /\ \E srcHash \in Hash :
            LET newRcvBlock ==
                [previous   |-> prevHash,
                source      |-> srcHash,
                type        |-> "receive"]
            IN
            /\ ValidateReceiveBlock(ledger, newRcvBlock)
            /\ CalculateHash(newRcvBlock, lastHash, lastHash')
            /\ received' =
                LET signedRcvBlock ==
                    [block      |-> newRcvBlock,
                    signature   |-> SignHash(lastHash', privateKey)]
                IN
                [n \in Node |->
                    received[n] \cup {signedRcvBlock}]
            /\ UNCHANGED distributedLedger

ProcessReceiveBlock(node, signedBlock) ==
    LET
      block == signedBlock.block
      ledger == distributedLedger[node]
    IN
    /\ ValidateReceiveBlock(ledger, block)
    /\ ~IsSendReceived(ledger, block.source)
    /\ CalculateHash(block, lastHash, lastHash')
    /\ ValidateSignature(
        signedBlock.signature,
        PublicKeyOf(ledger, block.previous),
        lastHash')
    /\ distributedLedger' =
        [distributedLedger EXCEPT
            ![node][lastHash'] = signedBlock]

ValidateChangeBlock(ledger, block) ==
    /\ block.type = "change"
    /\ ledger[block.previous] /= NoBlock

CreateChangeRepBlock(node) ==
    LET
      privateKey == Ownership[node]
      publicKey == KeyPair[privateKey]
      ledger == distributedLedger[node]
    IN
    /\ \E prevHash \in Hash :
        /\ ledger[prevHash] /= NoBlock
        /\ PublicKeyOf(ledger, prevHash) = publicKey
        /\ \E newRep \in PublicKey :
            LET newChangeRepBlock ==
                [previous   |-> prevHash,
                rep         |-> newRep,
                type        |-> "change"]
            IN
            /\ ValidateChangeBlock(ledger, newChangeRepBlock)
            /\ CalculateHash(newChangeRepBlock, lastHash, lastHash')
            /\ received' =
                LET signedChangeRepBlock ==
                    [block      |-> newChangeRepBlock,
                    signature   |-> SignHash(lastHash', privateKey)]
                IN
                [n \in Node |->
                    received[n] \cup {signedChangeRepBlock}]
            /\ UNCHANGED distributedLedger

ProcessChangeRepBlock(node, signedBlock) ==
    LET
      block == signedBlock.block
      ledger == distributedLedger[node]
    IN
    /\ ValidateChangeBlock(ledger, block)
    /\ CalculateHash(block, lastHash, lastHash')
    /\ ValidateSignature(
        signedBlock.signature,
        PublicKeyOf(ledger, block.previous),
        lastHash')
    /\ distributedLedger' =
        [distributedLedger EXCEPT
            ![node][lastHash'] = signedBlock]

CreateBlock(node) ==
    \/ CreateOpenBlock(node)
    \/ CreateSendBlock(node)
    \/ CreateReceiveBlock(node)
    \/ CreateChangeRepBlock(node)

ProcessBlock(node) ==
    /\ \E block \in received[node] :
        /\  \/ ProcessOpenBlock(node, block)
            \/ ProcessSendBlock(node, block)
            \/ ProcessReceiveBlock(node, block)
            \/ ProcessChangeRepBlock(node, block)
        /\ received' = [received EXCEPT ![node] = @ \ {block}]

Init ==
    /\ lastHash = NoHash
    /\ distributedLedger = [n \in Node |-> [h \in Hash |-> NoBlock]]
    /\ received = [n \in Node |-> {}]

Next ==
    \/ \E account \in PrivateKey : CreateGenesisBlock(account)
    \/ \E node \in Node : CreateBlock(node)
    \/ \E node \in Node : ProcessBlock(node)

Spec ==
    /\ Init
    /\ [][Next]_<<lastHash, distributedLedger, received>>

=============================================================================

