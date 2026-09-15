------------------ MODULE ivy_examples_alternating_bit_protocolModel ------------------
EXTENDS Naturals, Sequences, TLAPS

CONSTANTS Value, Bot

DataValue == Value \ {Bot}

ASSUME ValueAssumption ==
  /\ Bot \in Value
  /\ DataValue # {}

VARIABLES
  sender_array, receiver_array,
  sender_i, sender_gen_i, receiver_i,
  sender_bit, receiver_bit,
  data_chan, ack_chan

vars ==
  << sender_array, receiver_array,
     sender_i, sender_gen_i, receiver_i,
     sender_bit, receiver_bit,
     data_chan, ack_chan >>

RemoveAt(s, i) ==
  [j \in 1..(Len(s) - 1) |-> IF j < i THEN s[j] ELSE s[j + 1]]

Init ==
  /\ sender_array = [i \in Nat |-> Bot]
  /\ receiver_array = [i \in Nat |-> Bot]
  /\ sender_i = 0
  /\ sender_gen_i = 0
  /\ receiver_i = 0
  /\ sender_bit = FALSE
  /\ receiver_bit = FALSE
  /\ data_chan = <<>>
  /\ ack_chan = <<>>

GenerateData(v) ==
  /\ v \in DataValue
  /\ sender_array' = [sender_array EXCEPT ![sender_gen_i] = v]
  /\ sender_gen_i' = sender_gen_i + 1
  /\ UNCHANGED << receiver_array, sender_i, receiver_i,
                  sender_bit, receiver_bit, data_chan, ack_chan >>

SenderSendData ==
  /\ sender_array[sender_i] # Bot
  /\ data_chan' =
       Append(data_chan, [value |-> sender_array[sender_i],
                          bit   |-> sender_bit])
  /\ UNCHANGED << sender_array, receiver_array,
                  sender_i, sender_gen_i, receiver_i,
                  sender_bit, receiver_bit, ack_chan >>

SenderReceiveAck ==
  /\ ack_chan # <<>>
  /\ ack_chan' = Tail(ack_chan)
  /\ IF Head(ack_chan) = sender_bit
       THEN /\ sender_bit' = ~sender_bit
            /\ sender_i' = sender_i + 1
       ELSE /\ sender_bit' = sender_bit
            /\ sender_i' = sender_i
  /\ UNCHANGED << sender_array, receiver_array,
                  sender_gen_i, receiver_i, receiver_bit, data_chan >>

ReceiverReceiveData ==
  /\ data_chan # <<>>
  /\ data_chan' = Tail(data_chan)
  /\ LET msg == Head(data_chan) IN
       IF msg.bit = receiver_bit
          THEN /\ receiver_bit' = ~receiver_bit
               /\ receiver_array' =
                    [receiver_array EXCEPT ![receiver_i] = msg.value]
               /\ receiver_i' = receiver_i + 1
          ELSE /\ receiver_bit' = receiver_bit
               /\ receiver_array' = receiver_array
               /\ receiver_i' = receiver_i
  /\ UNCHANGED << sender_array, sender_i, sender_gen_i,
                  sender_bit, ack_chan >>

ReceiverSendAck ==
  /\ ack_chan' = Append(ack_chan, ~receiver_bit)
  /\ UNCHANGED << sender_array, receiver_array,
                  sender_i, sender_gen_i, receiver_i,
                  sender_bit, receiver_bit, data_chan >>

DataMsgDrop(i) ==
  /\ i \in 1..Len(data_chan)
  /\ data_chan' = RemoveAt(data_chan, i)
  /\ UNCHANGED << sender_array, receiver_array,
                  sender_i, sender_gen_i, receiver_i,
                  sender_bit, receiver_bit, ack_chan >>

AckMsgDrop(i) ==
  /\ i \in 1..Len(ack_chan)
  /\ ack_chan' = RemoveAt(ack_chan, i)
  /\ UNCHANGED << sender_array, receiver_array,
                  sender_i, sender_gen_i, receiver_i,
                  sender_bit, receiver_bit, data_chan >>

Next ==
  \/ \E v \in DataValue : GenerateData(v)
  \/ SenderSendData
  \/ SenderReceiveAck
  \/ ReceiverReceiveData
  \/ ReceiverSendAck
  \/ \E i \in 1..Len(data_chan) : DataMsgDrop(i)
  \/ \E i \in 1..Len(ack_chan) : AckMsgDrop(i)

SafetySpec ==
  /\ Init
  /\ [][Next]_vars

=============================================================================
