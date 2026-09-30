---- MODULE PirateShip ----

EXTENDS 
    
    Integers, 
    Sequences, 
    FiniteSets,
    
    FiniteSetsExt, 
    SequencesExt

----

CONSTANT R
ASSUME R # {}
ASSUME ReplicaSetFinite == IsFiniteSet(R)

CONSTANT u
ASSUME u \in Nat /\ u < Cardinality(R)

CONSTANT fsafe
ASSUME fsafe \in Nat

CONSTANT BR
ASSUME BR \subseteq R /\ Cardinality(BR) <= fsafe

ASSUME Cardinality(R) >= 2*u + fsafe + 1

CONSTANT Txs
ASSUME Txs # {}

ASSUME DistinguishedTransaction == 1 \in Txs

CONSTANT MaxByzActions
ASSUME ByzantineBudgetNatural == MaxByzActions \in Nat

----

VARIABLE

    network,
    
    view,
    
    branch,
    
    leader,
    
    prepareQC,
    
    commitIndex,
    
    auditIndex,
    
    byzActions,
    
    viewStable

vars == <<
    network,
    view,  
    branch,
    leader,
    prepareQC,
    commitIndex,
    auditIndex,
    byzActions,
    viewStable>>

----

N == Cardinality(R)

CQ == {q \in SUBSET R: Cardinality(q) >= N - ((N-1) \div 2)}

AQ == {q \in SUBSET R: Cardinality(q) >= N - u}

HR == R \ BR

ReplicaSeq ==
    CHOOSE s \in [ 1..N -> R ]: Range(s) = R

Leader(v) ==
    ReplicaSeq[(v % N) + 1]

----

Init == 
    /\ view = [r \in R |-> 0]
    /\ network = [r \in R |-> [s \in R |-> <<>>]]
    /\ branch = [r \in R |-> <<>>]
    /\ leader \in { f \in [ R -> BOOLEAN ] : Cardinality({ r \in R : f[r] }) = 1 }
    /\ prepareQC = [r \in R |-> [s \in R |-> 0]]
    /\ commitIndex = [r \in R |-> 0]
    /\ auditIndex = [r \in R |-> 0]
    /\ byzActions = 0
    /\ viewStable = leader

----

IsAuditQC(batch) ==
    batch.auditQC # {}

IsCommitQC(batch) ==
    batch.commitQC # {}

HighestCommitQC(b) ==
    LET idx == SelectLastInSeq(b, IsCommitQC)
    IN IF idx = 0 THEN 0 ELSE Max(b[idx].commitQC)

HighestAuditQC(b) ==
    LET idx == SelectLastInSeq(b, IsAuditQC)
    IN IF idx = 0 THEN 0 ELSE Max(b[idx].auditQC)

HighestQCOverQC(b) ==
    LET auditQCIndex == HighestAuditQC(b)
        idx == SelectLastInSubSeq(b, 1, auditQCIndex, IsAuditQC)
    IN IF idx = 0 THEN 0 ELSE Max(b[idx].auditQC)

UnanimityScan(b, idx, r) ==
    LET V(S, i) == S \cup b[i].auditQCVotes \cup IF i <= idx THEN {r} ELSE {}
        RUnanimity[i \in 0..Len(b)] ==
            IF i = 0 THEN [S \in SUBSET R |-> {0}]
            ELSE [S \in SUBSET R |->
                IF V(S, i) = R THEN b[i].auditQC
                ELSE RUnanimity[i-1][V(S, i)]]
    IN RUnanimity

HighestUnanimity(b, idx, r) ==
    UnanimityScan(b, idx, r)[Len(b)][{}]

Max2(a,b) == IF a > b THEN a ELSE b
Min2(a,b) == IF a < b THEN a ELSE b

QuorumScan(Q, b, m, default) ==
    LET RMaxQuorum[i \in default..Len(b)] ==
            IF i = default THEN default
            ELSE IF \E q \in Q: \A n \in q: m[n] >= i
                 THEN i ELSE RMaxQuorum[i-1]
    IN RMaxQuorum

MaxQuorum(Q, b, m, default) ==
    QuorumScan(Q, b, m, default)[Len(b)]

WellFormedBranch(b) ==
    \A i \in DOMAIN b :
        
        /\ i > 1 => b[i-1].view <= b[i].view
        
        /\ \A q \in b[i].auditQC :
            
            /\ q < i
            
            /\ b[q].view = b[i].view
            
            /\ \A j \in 1..i-1 : 
                \A qj \in b[j].auditQC: qj < q
        
        /\ \A q \in b[i].commitQC :
            
            /\ q < i
            
            /\ \A j \in 1..i-1 : 
                \A qj \in b[j].commitQC: qj < q

ReceiveEntries(r, p) ==
    
    /\ network[r][p] # <<>>
    
    /\ Head(network[r][p]).type = "AppendEntries"
    
    /\ view[r] = Head(network[r][p]).view
    
    /\ Last(Head(network[r][p]).branch).view = view[r]
    
    /\ branch[r] = Front(Head(network[r][p]).branch)
    
    /\ WellFormedBranch(Head(network[r][p]).branch)
    
    /\ branch' = [branch EXCEPT ![r] =  Head(network[r][p]).branch]
    
    /\ network' = [network EXCEPT 
        ![r][p] = Tail(@),
        ![p][r] = Append(@,[
            type |-> "Vote",
            view |-> view[r],
            branch |-> branch'[r]
            ])
        ]

    /\ commitIndex' = [commitIndex EXCEPT ![r] = Max2(@, HighestCommitQC(branch'[r]))]
    
    /\ LET AuditIndex == HighestQCOverQC(branch'[r])
           fastAuditIndexes == HighestUnanimity(branch'[r], 0, r)
       IN auditIndex' = [auditIndex EXCEPT ![r] = Max({@} \cup {AuditIndex} \cup fastAuditIndexes) ]
    /\ UNCHANGED <<leader, view, prepareQC, byzActions, viewStable>>

ReceiveNewView(r, p) ==
    
    /\ network[r][p] # <<>>
    
    /\ Head(network[r][p]).type = "NewView"
    
    /\ p = Leader(Head(network[r][p]).view)
    
    /\ view[r] \leq Head(network[r][p]).view
    
    /\ WellFormedBranch(Head(network[r][p]).branch)

    /\ view' = [view EXCEPT ![r] = Head(network[r][p]).view]
    
    /\ leader' = [leader EXCEPT ![r] = FALSE]
    /\ viewStable' = [viewStable EXCEPT ![r] = FALSE]
    
    /\ prepareQC' = [prepareQC EXCEPT ![r] = [s \in R |-> 0]]
    
    /\ branch' = [branch EXCEPT ![r] =  Head(network[r][p]).branch]
    
    /\ network' = [network EXCEPT 
        ![r][p] = Tail(@),
        ![p][r] = Append(@,[
            type |-> "Vote",
            view |-> view[r],
            branch |-> branch'[r]
            ])
        ]

    /\ commitIndex' = [commitIndex EXCEPT ![r] = Min2(@, Len(branch'[r]))]
    /\ UNCHANGED <<byzActions, auditIndex>>

CheckViewStability(p) ==
    LET inView(batch) == batch.view=view[p] IN
    \E Q \in AQ: 
        \A q \in Q: 
            prepareQC'[p][q] >= SelectInSeq(branch[p], inView)

ReceiveVote(p, r) ==
    
    /\ leader[p]
    
    /\ network[p][r] # <<>>
    /\ Head(network[p][r]).type = "Vote"
    /\ view[p] = Head(network[p][r]).view
    /\ prepareQC' = [prepareQC EXCEPT 
        ![p][r] = IF @ \leq Len(Head(network[p][r]).branch)
        THEN Len(Head(network[p][r]).branch)
        ELSE @]
    
    /\ network' = [network EXCEPT ![p][r] = Tail(network[p][r])]
    
    /\ viewStable' = [viewStable EXCEPT ![p] = 
            IF @ THEN @ ELSE CheckViewStability(p)]
    
    /\ IF viewStable'[p] THEN 
            /\ commitIndex' = [commitIndex EXCEPT ![p] = 
                MaxQuorum(CQ, branch[p], prepareQC'[p], @)]
            /\ LET AuditIndex == HighestAuditQC(SubSeq(branch[p], 1, MaxQuorum(AQ, branch[p], prepareQC'[p], 0)))
                   fastAuditIndexes == HighestUnanimity(branch[p], prepareQC'[p][r], r)
               IN auditIndex' = [auditIndex EXCEPT ![p] = Max({@} \cup fastAuditIndexes \cup {AuditIndex}) ]
        ELSE UNCHANGED <<commitIndex, auditIndex>>
    /\ UNCHANGED <<view, branch, leader, byzActions>>

MaxCommitQC(b,p) ==
    IF commitIndex[p] > HighestCommitQC(b)
    THEN {commitIndex[p]}
    ELSE {}

MaxAuditQC(b, m) ==
    LET idx == MaxQuorum(AQ, b, m, 0) IN
    IF idx > HighestAuditQC(b)
    THEN [n |-> {idx}, v |-> {r \in DOMAIN m : m[r] >= idx}]
    ELSE [n |-> {}, v |-> {}]

SendEntries(p) ==
    
    /\ leader[p]
    
    /\ viewStable[p]
    /\ \E tx \in Txs:
        
        /\ prepareQC' = [prepareQC EXCEPT ![p][p] = Len(branch[p]) + 1]
        
        /\ LET qc == MaxAuditQC(branch[p], prepareQC'[p]) IN
           branch' = [branch EXCEPT ![p] = Append(@, [
            view |-> view[p],
            
            tx |-> <<tx>>,
            commitQC |-> MaxCommitQC(branch[p], p),
            auditQC |-> qc.n,
            auditQCVotes |-> qc.v])]
        /\ network' = 
            [r \in R |-> [s \in R |->
                IF s # p \/ r=p THEN network[r][s] ELSE Append(network[r][s], [ 
                    type |-> "AppendEntries",
                    view |-> view[p],
                    branch |-> branch'[p]])]]
        /\ UNCHANGED <<view, leader, commitIndex, auditIndex, byzActions, viewStable>>

Timeout(r) ==
    /\ view' = [view EXCEPT ![r] = view[r] + 1]
    
    /\ network' = [network EXCEPT ![Leader(view'[r])][r] = Append(@, [
        type |-> "ViewChange",
        view |-> view'[r],
        branch |-> branch[r]])
        ]
    
    /\ leader' = [leader EXCEPT ![r] = FALSE]
    /\ viewStable' = [viewStable EXCEPT ![r] = FALSE]
    
    /\ prepareQC' = [prepareQC EXCEPT ![r] = [s \in R |-> 0]]
    /\ UNCHANGED <<branch, commitIndex, auditIndex, byzActions>>

HighestQCView(b) ==
    LET idx == HighestAuditQC(b) IN
    IF idx = 0 THEN -1 ELSE b[idx].view

BranchChoiceRule(b,bs) ==
    
    \/ \A b2 \in bs: b2 = <<>>
    \/ /\ b # <<>>
        
       /\ LET v1 == HighestQCView(b)
          IN \A b2 \in bs:
                
                b # b2 /\ b2 # <<>>
                =>  LET v2 == HighestQCView(b2) IN
                    
                    \/ v1 > v2
                    
                    \/ /\ v1 = v2
                       /\ \/ Last(b).view > Last(b2).view
                          \/ /\ Last(b).view = Last(b2).view
                             /\ Len(b) >= Len(b2)

BecomeLeader(r) ==
    
    /\ r = Leader(view[r])
    
    /\ \E q \in AQ:
        /\ \A n \in q: 
            /\ network[r][n] # <<>>
            /\ Head(network[r][n]).type = "ViewChange"
            /\ view[r] = Head(network[r][n]).view
        /\ \E b1 \in {Head(network[r][n]).branch : n \in q}:
            
            /\ BranchChoiceRule(b1, {Head(network[r][n]).branch : n \in q})
            
            /\ branch' = [branch EXCEPT ![r] = Append(b1, [
                view |-> view[r],
                tx |-> <<>>,
                commitQC |-> {},
                auditQC |-> {},
                auditQCVotes |-> {}])]
            /\ prepareQC' = [prepareQC EXCEPT ![r][r] = Len(branch'[r])]
        
        /\ network' = [r1 \in R |-> [r2 \in R |-> 
            IF r1 = r /\ r2 \in q 
            THEN Tail(network[r1][r2]) 
            ELSE IF r1 # r /\ r2 = r 
                THEN Append(network[r1][r2], [ 
                    type |-> "NewView",
                    view |-> view[r],
                    branch |-> branch'[r]])
                ELSE network[r1][r2]]]
    
    /\ leader' = [leader EXCEPT ![r] = TRUE]

    /\ commitIndex' = [commitIndex EXCEPT 
        ![r] = Max2(Min2(@, Len(branch'[r])), HighestCommitQC(branch'[r]))]
    /\ UNCHANGED <<view, byzActions, auditIndex, viewStable>>

DiscardMessages ==
    /\ \E s,r \in R:
            network' = [network EXCEPT ![r][s] = SelectSeq(@, 
                LAMBDA m: ~(m.view < view[r] \/ 
                    (m.view = view[r] /\ m.type = "ViewChange" /\ leader[r])))]
    /\ UNCHANGED <<view, branch, leader, prepareQC, commitIndex, auditIndex, byzActions, viewStable>>

----

ByzOmitEntries(r, p) ==
    /\ r \in BR
    /\ byzActions < MaxByzActions
    /\ byzActions' = byzActions + 1
    
    /\ network[r][p] # <<>>
    
    /\ Head(network[r][p]).type = "AppendEntries"
    
    /\ view[r] = Head(network[r][p]).view
    
    /\ branch[r] = Front(Head(network[r][p]).branch)
    
    /\ network' = [network EXCEPT 
        ![r][p] = Tail(@),
        ![p][r] = Append(@,[
            type |-> "Vote",
            view |-> view[r],
            branch |-> Head(network[r][p]).branch
            ])
        ]
    /\ UNCHANGED <<leader, view, prepareQC, commitIndex, auditIndex, branch, viewStable>>

ModifyAppendEntries(m) == [
    type |-> "AppendEntries",
    view |-> m.view,
    branch |-> SubSeq(m.branch,1,Len(m.branch)-1) \o
        <<[Last(m.branch) EXCEPT !.tx = <<1>>]>>
]

ByzLeaderEquivocate(p) ==
    /\ p \in BR
    /\ byzActions < MaxByzActions
    /\ byzActions' = byzActions + 1
    /\ \E r \in R:
        /\ network[r][p] # <<>>
        /\ Head(network[r][p]).type = "AppendEntries"
        /\ Head(network[r][p]).branch # <<>>
        /\ network' = [network EXCEPT 
            ![r][p][1] = ModifyAppendEntries(@)]
    /\ UNCHANGED <<view, branch, leader, prepareQC, commitIndex, auditIndex, viewStable>>

Next == 
    \/ DiscardMessages
    \/ \E r \in BR:
        \/ ByzLeaderEquivocate(r)
        \/ \E s \in R: 
            ByzOmitEntries(r,s)
    \/ \E r \in R: 
        \/ SendEntries(r)
        \/ Timeout(r)
        \/ BecomeLeader(r)
        \/ \E s \in R: 
            \/ ReceiveEntries(r,s)
            \/ ReceiveVote(r,s)
            \/ ReceiveNewView(r,s)

Fairness ==
    
    /\ WF_vars(DiscardMessages)
    /\ \A r \in HR: WF_vars(TRUE \notin Range(leader) /\ Timeout(r))
    /\ \A r \in HR: WF_vars(BecomeLeader(r))
    /\ \A r \in HR: WF_vars(SendEntries(r))
    /\ \A r,s \in HR: WF_vars(ReceiveEntries(r,s))
    /\ \A r,s \in HR: WF_vars(ReceiveVote(r,s))
    /\ \A r,s \in HR: WF_vars(ReceiveNewView(r,s))

Spec == 
    /\ Init
    /\ [][Next]_vars
    /\ Fairness

----

CR == IF byzActions = 0 THEN R ELSE HR

MonotonicAuditedIndexProp ==
    [][\A i \in CR :
        auditIndex[i] <= auditIndex'[i]]_vars

====
