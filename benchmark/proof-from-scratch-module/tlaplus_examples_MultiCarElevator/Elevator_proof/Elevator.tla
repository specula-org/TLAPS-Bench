------------------------------ MODULE Elevator ------------------------------

EXTENDS     Integers

CONSTANTS   Person,     
            Elevator,   
            FloorCount  

VARIABLES   PersonState,            
            ActiveElevatorCalls,    
            ElevatorState           

Vars == 
    <<PersonState, ActiveElevatorCalls, ElevatorState>>

Floor ==    
    1 .. FloorCount

Direction ==    
    {"Up", "Down"}

ElevatorCall == 
    [floor : Floor, direction : Direction]

ElevatorDirectionState ==   
    Direction \cup {"Stationary"}

GetDistance[f1, f2 \in Floor] ==    
    IF f1 > f2 THEN f1 - f2 ELSE f2 - f1
    
GetDirection[current, destination \in Floor] == 
    IF destination > current THEN "Up" ELSE "Down"

CanServiceCall[e \in Elevator, c \in ElevatorCall] ==   
    LET eState == ElevatorState[e] IN
    /\ c.floor = eState.floor
    /\ c.direction = eState.direction

PeopleWaiting[f \in Floor, d \in Direction] ==  
    {p \in Person :
        /\ PersonState[p].location = f
        /\ PersonState[p].waiting
        /\ GetDirection[PersonState[p].location, PersonState[p].destination] = d}

TypeInvariant ==    
    /\ PersonState \in [Person -> [location : Floor \cup Elevator, destination : Floor, waiting : BOOLEAN]]
    /\ ActiveElevatorCalls \subseteq ElevatorCall
    /\ ElevatorState \in [Elevator -> [floor : Floor, direction : ElevatorDirectionState, doorsOpen : BOOLEAN, buttonsPressed : SUBSET Floor]]

SafetyInvariant ==   
    /\ \A e \in Elevator :  
        /\ \A f \in ElevatorState[e].buttonsPressed :
            /\ \E p \in Person :
                /\ PersonState[p].location = e
                /\ PersonState[p].destination = f
    /\ \A p \in Person :    
        /\ \A e \in Elevator :
            /\ (PersonState[p].location = e /\ ElevatorState[e].floor /= PersonState[p].destination) => 
                /\ ElevatorState[e].direction = GetDirection[ElevatorState[e].floor, PersonState[p].destination]
    /\ \A c \in ActiveElevatorCalls : PeopleWaiting[c.floor, c.direction] /= {} 

PickNewDestination(p) ==    
    LET pState == PersonState[p] IN
    /\ ~pState.waiting
    /\ pState.location \in Floor
    /\ \E f \in Floor :
        /\ f /= pState.location
        /\ PersonState' = [PersonState EXCEPT ![p] = [@ EXCEPT !.destination = f]]
    /\ UNCHANGED <<ActiveElevatorCalls, ElevatorState>>

CallElevator(p) ==  
    LET
      pState == PersonState[p]
      call == [floor |-> pState.location, direction |-> GetDirection[pState.location, pState.destination]]
    IN
    /\ ~pState.waiting
    /\ pState.location /= pState.destination
    /\ ActiveElevatorCalls' =
        IF \E e \in Elevator :
            /\ CanServiceCall[e, call]
            /\ ElevatorState[e].doorsOpen
        THEN ActiveElevatorCalls
        ELSE ActiveElevatorCalls \cup {call}
    /\ PersonState' = [PersonState EXCEPT ![p] = [@ EXCEPT !.waiting = TRUE]]
    /\ UNCHANGED <<ElevatorState>>

OpenElevatorDoors(e) == 
    LET eState == ElevatorState[e] IN
    /\ ~eState.doorsOpen
    /\  \/ \E call \in ActiveElevatorCalls : CanServiceCall[e, call]
        \/ eState.floor \in eState.buttonsPressed
    /\ ElevatorState' = [ElevatorState EXCEPT ![e] = [@ EXCEPT !.doorsOpen = TRUE, !.buttonsPressed = @ \ {eState.floor}]]
    /\ ActiveElevatorCalls' = ActiveElevatorCalls \ {[floor |-> eState.floor, direction |-> eState.direction]}
    /\ UNCHANGED <<PersonState>>
    
EnterElevator(e) == 
    LET
      eState == ElevatorState[e]
      gettingOn == PeopleWaiting[eState.floor, eState.direction]
      destinations == {PersonState[p].destination : p \in gettingOn}
    IN
    /\ eState.doorsOpen
    /\ eState.direction /= "Stationary"
    /\ gettingOn /= {}
    /\ PersonState' = [p \in Person |->
        IF p \in gettingOn
        THEN [PersonState[p] EXCEPT !.location = e]
        ELSE PersonState[p]]
    /\ ElevatorState' = [ElevatorState EXCEPT ![e] = [@ EXCEPT !.buttonsPressed = @ \cup destinations]]
    /\ UNCHANGED <<ActiveElevatorCalls>>

ExitElevator(e) ==  
    LET
      eState == ElevatorState[e]
      gettingOff == {p \in Person : PersonState[p].location = e /\ PersonState[p].destination = eState.floor}
    IN
    /\ eState.doorsOpen
    /\ gettingOff /= {}
    /\ PersonState' = [p \in Person |->
        IF p \in gettingOff
        THEN [PersonState[p] EXCEPT !.location = eState.floor, !.waiting = FALSE]
        ELSE PersonState[p]]
    /\ UNCHANGED <<ActiveElevatorCalls, ElevatorState>>

CloseElevatorDoors(e) ==    
    LET eState == ElevatorState[e] IN
    /\ ~ENABLED EnterElevator(e)
    /\ ~ENABLED ExitElevator(e)
    /\ eState.doorsOpen
    /\ ElevatorState' = [ElevatorState EXCEPT ![e] = [@ EXCEPT !.doorsOpen = FALSE]]
    /\ UNCHANGED <<PersonState, ActiveElevatorCalls>>

MoveElevator(e) ==  
    LET
      eState == ElevatorState[e]
      nextFloor == IF eState.direction = "Up" THEN eState.floor + 1 ELSE eState.floor - 1
    IN
    /\ eState.direction /= "Stationary"
    /\ ~eState.doorsOpen
    /\ eState.floor \notin eState.buttonsPressed
    /\ \A call \in ActiveElevatorCalls : 
        /\ CanServiceCall[e, call] =>
            /\ \E e2 \in Elevator :
                /\ e /= e2
                /\ CanServiceCall[e2, call]
    /\ nextFloor \in Floor
    /\ ElevatorState' = [ElevatorState EXCEPT ![e] = [@ EXCEPT !.floor = nextFloor]]
    /\ UNCHANGED <<PersonState, ActiveElevatorCalls>>

StopElevator(e) == 
    LET
      eState == ElevatorState[e]
      nextFloor == IF eState.direction = "Up" THEN eState.floor + 1 ELSE eState.floor - 1
    IN
    /\ ~ENABLED OpenElevatorDoors(e)
    /\ ~eState.doorsOpen
    /\ nextFloor \notin Floor
    /\ ElevatorState' = [ElevatorState EXCEPT ![e] = [@ EXCEPT !.direction = "Stationary"]]
    /\ UNCHANGED <<PersonState, ActiveElevatorCalls>>

DispatchElevator(c) ==
    LET
      stationary == {e \in Elevator : ElevatorState[e].direction = "Stationary"}
      approaching == {e \in Elevator :
        /\ ElevatorState[e].direction = c.direction
        /\  \/ ElevatorState[e].floor = c.floor
            \/ GetDirection[ElevatorState[e].floor, c.floor] = c.direction }
    IN
    /\ c \in ActiveElevatorCalls
    /\ stationary \cup approaching /= {}
    /\ ElevatorState' = 
        LET closest == CHOOSE e \in stationary \cup approaching :
            /\ \A e2 \in stationary \cup approaching :
                /\ GetDistance[ElevatorState[e].floor, c.floor] <= GetDistance[ElevatorState[e2].floor, c.floor] IN
        IF closest \in stationary
        THEN [ElevatorState EXCEPT ![closest] = [@ EXCEPT !.floor = c.floor, !.direction = c.direction]]
        ELSE ElevatorState
    /\ UNCHANGED <<PersonState, ActiveElevatorCalls>>

Init == 
    /\ PersonState \in [Person -> [location : Floor, destination : Floor, waiting : {FALSE}]]
    /\ ActiveElevatorCalls = {}
    /\ ElevatorState \in [Elevator -> [floor : Floor, direction : {"Stationary"}, doorsOpen : {FALSE}, buttonsPressed : {{}}]]

Next == 
    \/ \E p \in Person : PickNewDestination(p)
    \/ \E p \in Person : CallElevator(p)
    \/ \E e \in Elevator : OpenElevatorDoors(e)
    \/ \E e \in Elevator : EnterElevator(e)
    \/ \E e \in Elevator : ExitElevator(e)
    \/ \E e \in Elevator : CloseElevatorDoors(e)
    \/ \E e \in Elevator : MoveElevator(e)
    \/ \E e \in Elevator : StopElevator(e)
    \/ \E c \in ElevatorCall : DispatchElevator(c)

TemporalAssumptions ==  
    /\ \A p \in Person : WF_Vars(CallElevator(p))
    /\ \A e \in Elevator : WF_Vars(OpenElevatorDoors(e))
    /\ \A e \in Elevator : WF_Vars(EnterElevator(e))
    /\ \A e \in Elevator : WF_Vars(ExitElevator(e))
    /\ \A e \in Elevator : SF_Vars(CloseElevatorDoors(e))
    /\ \A e \in Elevator : SF_Vars(MoveElevator(e))
    /\ \A e \in Elevator : WF_Vars(StopElevator(e))
    /\ \A c \in ElevatorCall : SF_Vars(DispatchElevator(c))

Spec == 
    /\ Init
    /\ [][Next]_Vars
    /\ TemporalAssumptions

=============================================================================

