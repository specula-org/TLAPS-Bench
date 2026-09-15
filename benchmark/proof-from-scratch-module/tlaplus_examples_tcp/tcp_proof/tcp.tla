------------------------------- MODULE tcp ----------------------------------

EXTENDS Integers, Sequences, SequencesExt, FiniteSets

CONSTANT 
    Peers

ASSUME PeersAssumption == Cardinality(Peers) = 2

States == {"LISTEN", "CLOSED", "SYN-SENT", "SYN-RECEIVED", "ESTABLISHED", 
          "FIN-WAIT-1", "FIN-WAIT-2", "CLOSING", "CLOSE-WAIT", "LAST-ACK",
          "TIME-WAIT"}

VARIABLE
    tcb,
    connstate,
    network

vars == <<tcb, connstate, network>>

TypeOK ==
    /\ tcb \in [ Peers -> BOOLEAN ]
    /\ connstate \in [ Peers -> States ]
    /\ network \in [ Peers -> Seq({"SYN", "SYN,ACK", "ACK", "RST", "FIN"} \cup {"ACKofFIN"}) ]

Init ==
    /\ tcb = [p \in Peers |-> FALSE]
    /\ connstate = [p \in Peers |-> "CLOSED"]
    /\ network = [p \in Peers |-> <<>>]

PASSIVE_OPEN(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "CLOSED"
    /\ UNCHANGED network
    /\ connstate' = [connstate EXCEPT ![local] = "LISTEN"]
    /\ tcb' = [tcb EXCEPT ![local] = TRUE]

ACTIVE_OPEN(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "CLOSED"
    /\ network' = [ network EXCEPT ![remote] = Append(@, "SYN")]
    /\ connstate' = [connstate EXCEPT ![local] = "SYN-SENT"]
    /\ tcb' = [tcb EXCEPT ![local] = TRUE]

CLOSE_SYN_SENT(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "SYN-SENT"
    /\ UNCHANGED network
    /\ connstate' = [connstate EXCEPT ![local] = "CLOSED"]
    /\ tcb' = [tcb EXCEPT ![local] = FALSE]

CLOSE_SYN_RECEIVED(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "SYN-RECEIVED"
    /\ network' = [ network EXCEPT ![remote] = Append(@, "FIN")]
    /\ connstate' = [connstate EXCEPT ![local] = "FIN-WAIT-1"]
    /\ UNCHANGED tcb

SEND(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "LISTEN"
    /\ network' = [ network EXCEPT ![remote] = Append(@, "SYN")]
    /\ connstate' = [connstate EXCEPT ![local] = "SYN-SENT"]
    /\ UNCHANGED tcb

CLOSE_LISTEN(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "LISTEN"
    /\ UNCHANGED network
    /\ connstate' = [connstate EXCEPT ![local] = "CLOSED"]
    /\ tcb' = [tcb EXCEPT ![local] = FALSE]

CLOSE_ESTABLISHED(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "ESTABLISHED"
    /\ network' = [ network EXCEPT ![remote] = Append(@, "FIN")]
    /\ connstate' = [connstate EXCEPT ![local] = "FIN-WAIT-1"]
    /\ UNCHANGED tcb

CLOSE_CLOSE_WAIT(local, remote) ==
    
    /\ local # remote
    /\ connstate[local] = "CLOSE-WAIT"
    /\ network' = [ network EXCEPT ![remote] = Append(@, "FIN")]
    /\ connstate' = [connstate EXCEPT ![local] = "LAST-ACK"]
    /\ UNCHANGED tcb

User ==
    \E local, remote \in Peers :
        \/ ACTIVE_OPEN(local, remote)
        \/ PASSIVE_OPEN(local, remote)
        \/ CLOSE_SYN_SENT(local, remote)
        \/ CLOSE_SYN_RECEIVED(local, remote)
        \/ CLOSE_LISTEN(local, remote)
        \/ CLOSE_ESTABLISHED(local, remote)
        \/ CLOSE_CLOSE_WAIT(local, remote)
        \/ SEND(local, remote)

-----------------------------------------------------------------------------
       
SynSent(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "SYN-SENT"
    /\ UNCHANGED tcb
    /\ \/ /\ IsPrefix(<<"SYN">>, network[local])
          /\ network' = [ network EXCEPT ![remote] = Append(@, "SYN,ACK"),
                                         ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "SYN-RECEIVED"]
       \/ /\ IsPrefix(<<"SYN,ACK">>, network[local])
          /\ network' = [ network EXCEPT ![remote] = Append(@, "ACK"),
                                         ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "ESTABLISHED"]

SynReceived(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "SYN-RECEIVED"
    /\ UNCHANGED tcb
    /\ \/ /\ IsPrefix(<<"RST">>, network[local]) 
          /\ network' = [ network EXCEPT ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "LISTEN"]
       \/ /\ IsPrefix(<<"ACK">>, network[local]) 
          /\ network' = [ network EXCEPT ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "ESTABLISHED"]

Listen(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "LISTEN"
    /\ UNCHANGED tcb
    /\ \/ /\ IsPrefix(<<"SYN">>, network[local])
          /\ network' = [ network EXCEPT ![remote] = Append(@, "SYN,ACK"),
                                         ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "SYN-RECEIVED"]

Established(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "ESTABLISHED"
    /\ UNCHANGED tcb
    /\ IsPrefix(<<"FIN">>, network[local])
    /\ network' = [ network EXCEPT ![remote] = Append(@, "ACKofFIN"),
                                   ![local] = Tail(network[local])]
    /\ connstate' = [connstate EXCEPT ![local] = "CLOSE-WAIT"]

-----------------------------------------------------------------------------

FinWait1(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "FIN-WAIT-1"
    /\ UNCHANGED tcb
    /\ \/ /\ IsPrefix(<<"FIN">>, network[local])
          /\ network' = [ network EXCEPT ![remote] = Append(@, "ACKofFIN"),
                                         ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "CLOSING"]
       \/ /\ IsPrefix(<<"ACKofFIN">>, network[local])
          /\ network' = [ network EXCEPT ![local] = Tail(network[local])]
          /\ connstate' = [connstate EXCEPT ![local] = "FIN-WAIT-2"]

FinWait2(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "FIN-WAIT-2"
    /\ UNCHANGED tcb
    /\ IsPrefix(<<"FIN">>, network[local])
    /\ network' = [ network EXCEPT ![remote] = Append(@, "ACKofFIN"),
                                   ![local] = Tail(network[local])]
    /\ connstate' = [connstate EXCEPT ![local] = "TIME-WAIT"]

Closing(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "CLOSING"
    /\ UNCHANGED tcb
    /\ IsPrefix(<<"ACKofFIN">>, network[local])
    /\ network' = [ network EXCEPT ![local] = Tail(network[local])]
    /\ connstate' = [connstate EXCEPT ![local] = "TIME-WAIT"]

LastAck(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "LAST-ACK"
    /\ UNCHANGED tcb
    /\ IsPrefix(<<"ACKofFIN">>, network[local])
    /\ network' = [ network EXCEPT ![local] = Tail(network[local])]
    /\ connstate' = [connstate EXCEPT ![local] = "CLOSED"]

TimeWait(local, remote) ==
    /\ local # remote
    /\ connstate[local] = "TIME-WAIT"
    /\ tcb[local]
    /\ UNCHANGED network
    /\ connstate' = [connstate EXCEPT ![local] = "CLOSED"]
    /\ tcb' = [tcb EXCEPT ![local] = FALSE]

Note2(local, remote) ==

    /\ local # remote
    /\ connstate[local] = "FIN-WAIT-1"
    /\ UNCHANGED tcb
    
    /\ IsPrefix(<< "FIN", "ACKofFIN" >>, network[local])
    
    /\ network' = [ network EXCEPT ![remote] = Append(@, "ACKofFIN"),
                                   ![local] = SubSeq(network[local], 3, Len(network[local]))]
    /\ connstate' = [connstate EXCEPT ![local] = "TIME-WAIT"]

System ==
    \E local, remote \in Peers :
        \/ SynSent(local, remote)
        \/ SynReceived(local, remote)
        \/ Listen(local, remote)
        \/ Established(local, remote)
        \/ FinWait1(local, remote)
        \/ FinWait2(local, remote)
        \/ Closing(local, remote)
        \/ LastAck(local, remote)
        \/ TimeWait(local, remote)
        \/ Note2(local, remote)

Note3(local, remote) ==

    /\ local # remote
    /\ UNCHANGED tcb
    /\ \/ /\ tcb[local] 
          /\ network' = [ network EXCEPT ![remote] = Append(@, "RST")]
          /\ connstate' = [connstate EXCEPT ![local] = "TIME-WAIT"]
       \/ /\ IsPrefix(<<"RST">>, network[local])
          /\ network' = [ network EXCEPT ![local] = Tail(network[local])]
          /\ \/ connstate' = [connstate EXCEPT ![local] = "LISTEN"]
             \/ connstate' = [connstate EXCEPT ![local] = "CLOSED"]

Reset ==
    \E local, remote \in Peers :
        Note3(local, remote)

Next ==
    \/ System
    \/ Reset
    \/ User

Spec ==
    /\ Init
    /\ [][Next]_vars
    /\ WF_vars(System)
    
    /\ WF_vars(\E local, remote \in Peers: CLOSE_SYN_SENT(local, remote))

-----------------------------------------------------------------------------

Inv ==

    \A local, remote \in { p \in Peers : network[p] = <<>> } :
        connstate[local] = "ESTABLISHED" <=> connstate[remote] = "ESTABLISHED"

=============================================================================
