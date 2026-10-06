---- MODULE pirateship ----
\* This is a TLA+ specification of the PirateShip consensus protocol.

EXTENDS 
    \* TLA+ standard modules
    Integers, 
    Sequences, 
    FiniteSets,
    \* TLA+ community modules
    FiniteSetsExt, 
    SequencesExt

----
\*  CONSTANTS

\* Set of all replicas
CONSTANT R
ASSUME R # {}

\* Maximum number of unavailable replicas
CONSTANT u
ASSUME u \in Nat /\ u < Cardinality(R)

\* Maximum number of Byzantine replicas tolerated for safety
CONSTANT fsafe
ASSUME fsafe \in Nat

\* Set of all Byzantine replicas
CONSTANT BR
ASSUME BR \subseteq R /\ Cardinality(BR) <= fsafe

\* PFT replication requirement
ASSUME Cardinality(R) >= 2*u + fsafe + 1

\* Set of all possible transactions
CONSTANT Txs
ASSUME Txs # {}

\* Maximum number of Byzantine actions across all replicas
\* This parameter is completely artificial and is used to limit the state space
CONSTANT MaxByzActions

----
\* VARIABLES

VARIABLE
    \* To reduce the state space, pairwise message delivery is modeled as ordered
    \* and reliable; no bound is placed on delivery time.
    \* messages in transit between any pair of replicas
    network,
    \* current view of each replica
    view,
    \* current branch of each replica
    branch,
    \* flag indicating if each replica is a leader
    leader,
    \* (leader only) the highest batch on each replica replicated in this view
    prepareQC,
    \* commit index of each replica
    commitIndex,
    \* audit index of each replica
    auditIndex,
    \* total number of Byzantine actions taken so far by any Byzantine replica
    byzActions,
    \* (leader only) flag indicating if the leader has stabilized the view
    viewStable

\* Sequence of all variables
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
\* HELPERS & VARIABLE TYPES

\* Number of replicas
\* For simplicity, we reason directly about replicas.
N == Cardinality(R)

\* Set of quorums for commitment (simple majority).
CQ == {q \in SUBSET R: Cardinality(q) >= N - ((N-1) \div 2)}

\* Set of quorums for auditing (all but u replicas).
AQ == {q \in SUBSET R: Cardinality(q) >= N - u}

\* Set of honest replicas
HR == R \ BR

\* Set of all views
Views ==  Nat

ReplicaSeq ==
    CHOOSE s \in [ 1..N -> R ]: Range(s) = R

\* The leader of view v
Leader(v) ==
    ReplicaSeq[(v % N) + 1]

\* Quorum certificates (QCs) are simply the index of the batch they confirm
\* Quorum certificates do not need views as they are always formed in the current view
\* Note that in the specification, we do not model signatures anywhere. 
\* This means that signatures are omitted from the branches and messages.
\* When modelling Byzantine faults, byz replicas will not be permitted to form
\* messages which would be discarded by honest replicas.
QC == Nat

\* Each batch contains a view, a txn and optionally, quorum certificates for commitment and auditing
\* We assume all transactions are signed.
Batch == [
    view: Views, 
    tx: Seq(Txs),
    \* For convenience, we represent a quorum certificate as a set but it can only be empty or a singleton
    auditQC: SUBSET QC,
    auditQCVotes: AQ \cup {{}}, \* empty set iff auditQC is empty.
    commitQC: SUBSET QC]

\* A branch is a sequence of batches. The index of the batch is its sequence number/height
\* We do not explicitly model the parent relationship, the parent of batch i is batch i-1
Branch == Seq(Batch)

\* Set of all possible AppendEntries messages
AppendEntries == [
    type: {"AppendEntries"},
    view: Views,
    \* In practice, it suffices to send only the batch to append
    \* However, for the sake of the spec, we send the entire branch as we need to check
    \* that the replica has the parent of the batch to append
    branch: Branch]

\* Set of all possible Vote messages
Votes == [
    type: {"Vote"},
    view: Views,
    \* As with AppendEntries, we send the entire branch for the sake of the spec
    branch: Branch]

\* Set of all possible ViewChange messages
ViewChanges == [
    type: {"ViewChange"},
    view: Views,
    branch: Branch]

\* Set of all possible NewView messages
\* Currently, we use separate messages for NewView and AppendEntries, these could be merged
NewViews == [
    type: {"NewView"},
    view: Views,
    branch: Branch]

\* Set of all possible messages
Messages == 
    AppendEntries \union 
    Votes \union 
    ViewChanges \union 
    NewViews

BranchTypeOK ==
    /\ branch \in [R -> Branch]
    /\ \A b \in Range(branch):
        \A i \in DOMAIN b: b[i].auditQC = {} <=> b[i].auditQCVotes = {}

NetworkTypeOK ==
    \A r, s \in R:
        \A i \in DOMAIN network[r][s]: 
            network[r][s][i] \in Messages

\* Invariant to check the types of all variables
TypeOK == 
    /\ viewStable \in [R -> BOOLEAN]
    /\ view \in [R -> Views]
    /\ BranchTypeOK
    /\ NetworkTypeOK
    /\ leader \in [R -> BOOLEAN]
    /\ prepareQC \in [R -> [R -> Nat]]
    /\ commitIndex \in [R -> Nat]
    /\ auditIndex \in [R -> Nat]
    /\ byzActions \in Nat

----
\* INITIAL STATES

\* We begin in view 0 with a non-deterministically chosen replica as leader.
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
\* ACTIONS

IsAuditQC(batch) ==
    batch.auditQC # {}

IsCommitQC(batch) ==
    batch.commitQC # {}

\* Given a branch b, returns the index of the highest batch with a commitQC, 0 if the branch contains no commitQCs
HighestCommitQC(b) ==
    LET idx == SelectLastInSeq(b, IsCommitQC)
    IN IF idx = 0 THEN 0 ELSE Max(b[idx].commitQC)

\* Given a branch b, returns the index of the highest batch with a auditQC, 0 if the branch contains no auditQCs
HighestAuditQC(b) ==
    LET idx == SelectLastInSeq(b, IsAuditQC)
    IN IF idx = 0 THEN 0 ELSE Max(b[idx].auditQC)

\* Given a branch b, returns the index of the highest batch with a auditQC over a auditQC
HighestQCOverQC(b) ==
    LET auditQCIndex == HighestAuditQC(b)
        idx == SelectLastInSubSeq(b, 1, auditQCIndex, IsAuditQC)
    IN IF idx = 0 THEN 0 ELSE Max(b[idx].auditQC)

\* Given a branch b, this operator returns the highest index of a batch for which a *Quorum Certificate* (QC)
\* exists. Note, the index of the batch with the QC corresponds to a higher branch index than the returned
\* index. This QC is formed by unanimous **auditQCVotes** from replicas.
\* Since a vote by a replica r for some index n implicitly serves as a vote for all batches at index b and
\* below, the returned highest index might not have directly received a unanimous vote.  Instead, replicas may
\* have voted for this index transitively by voting for higher indices.
\* The pair (idx, r) is a vote by replica r for branch index idx. While this vote may not yet be recorded in the
\* branch, this operator is robust against it.
HighestUnanimity(b, idx, r) ==
    \* Traverse the branch *backwards* and record the replicas that have voted for the current idx or higher
    \* indices (see V).
    LET \* Include r's vote in V of 1..i if r voted for index i.
        V(S, i) == S \cup b[i].auditQCVotes \cup IF i <= idx THEN {r} ELSE {}
        RECURSIVE RUnanimity(_,_)
        RUnanimity(i, S) ==
            IF i = 0 THEN {0}
            ELSE IF V(S, i) = R 
                 THEN b[i].auditQC
                 ELSE RUnanimity(i-1, V(S, i))
    IN RUnanimity(Len(b), {})

Max2(a,b) == IF a > b THEN a ELSE b
Min2(a,b) == IF a < b THEN a ELSE b

MaxQuorum(Q, b, m, default) ==
    LET RECURSIVE RMaxQuorum(_)
        RMaxQuorum(i) ==
            IF i = default THEN default
            ELSE IF \E q \in Q: \A n \in q: m[n] >= i
                 THEN i ELSE RMaxQuorum(i-1)
    IN RMaxQuorum(Len(b))

\* Checks if a branch b is well formed e.g. views are monotonically increasing
WellFormedBranch(b) ==
    \A i \in DOMAIN b :
        \* check views are monotonically increasing
        /\ i > 1 => b[i-1].view <= b[i].view
        \* check auditQCs are well formed
        /\ \A q \in b[i].auditQC :
            \* auditQCs are always for previous batches
            /\ q < i
            \* auditQCs are always formed in the current view 
            /\ b[q].view = b[i].view
            \* auditQCs are in increasing order
            /\ \A j \in 1..i-1 : 
                \A qj \in b[j].auditQC: qj < q
        \* check commitQCs are well formed
        /\ \A q \in b[i].commitQC :
            \* commitQCs are always for previous batches
            /\ q < i
            \* commitQCs are in increasing order
            /\ \A j \in 1..i-1 : 
                \A qj \in b[j].commitQC: qj < q

\* Replica r handling AppendEntries from leader p
ReceiveEntries(r, p) ==
    \* there must be at least one message pending
    /\ network[r][p] # <<>>
    \* and the next message is an AppendEntries
    /\ Head(network[r][p]).type = "AppendEntries"
    \* the replica must be in the same view
    /\ view[r] = Head(network[r][p]).view
    \* and must be replicating a batch from this view
    /\ Last(Head(network[r][p]).branch).view = view[r]
    \* the replica only appends (one batch at a time) to its branch
    /\ branch[r] = Front(Head(network[r][p]).branch)
    \* received branch must be well formed
    /\ WellFormedBranch(Head(network[r][p]).branch)
    \* for convenience, we replace the replica's branch with the received branch but in practice we are only appending one batch
    /\ branch' = [branch EXCEPT ![r] =  Head(network[r][p]).branch]
    \* we remove the AppendEntries message and reply with a Vote message.
    /\ network' = [network EXCEPT 
        ![r][p] = Tail(@),
        ![p][r] = Append(@,[
            type |-> "Vote",
            view |-> view[r],
            branch |-> branch'[r]
            ])
        ]
    \* replica updates its commit index provided the new commit index is greater than the current one
    \* the only time a commit index can decrease is on the receipt of a NewView message if there's been a byz attack
    /\ commitIndex' = [commitIndex EXCEPT ![r] = Max2(@, HighestCommitQC(branch'[r]))]
    \* assumes that a replica can safely consider a transaction audited if there's a quorum certificate over a quorum certificate
    /\ LET AuditIndex == HighestQCOverQC(branch'[r])
           fastAuditIndexes == HighestUnanimity(branch'[r], 0, r)
       IN auditIndex' = [auditIndex EXCEPT ![r] = Max({@} \cup {AuditIndex} \cup fastAuditIndexes) ]
    /\ UNCHANGED <<leader, view, prepareQC, byzActions, viewStable>>

\* Replica r handling NewView from leader p
\* Note that unlike an AppendEntries message, a replica can update its view upon receiving a NewView message
ReceiveNewView(r, p) ==
    \* there must be at least one message pending
    /\ network[r][p] # <<>>
    \* and the next message is a NewView
    /\ Head(network[r][p]).type = "NewView"
    \* and the message must be from the designated leader
    /\ p = Leader(Head(network[r][p]).view)
    \* the replica must be in the same view or lower
    /\ view[r] \leq Head(network[r][p]).view
    \* received branch must be well formed
    /\ WellFormedBranch(Head(network[r][p]).branch)
    \* update the replica's local view
    \* note that we do not dispatch a view change message as a leader has already been elected
    /\ view' = [view EXCEPT ![r] = Head(network[r][p]).view]
    \* step down if replica was a leader
    /\ leader' = [leader EXCEPT ![r] = FALSE]
    /\ viewStable' = [viewStable EXCEPT ![r] = FALSE]
    \* reset prepareQCs, in case view was updated
    /\ prepareQC' = [prepareQC EXCEPT ![r] = [s \in R |-> 0]]
    \* the replica replaces its branch with the received branch
    /\ branch' = [branch EXCEPT ![r] =  Head(network[r][p]).branch]
    \* we remove the NewView message and reply with a Vote message.
    /\ network' = [network EXCEPT 
        ![r][p] = Tail(@),
        ![p][r] = Append(@,[
            type |-> "Vote",
            view |-> view[r],
            branch |-> branch'[r]
            ])
        ]
    \* replica must update its commit index
    \* Commit index may be decreased if there's been an byz attack
    /\ commitIndex' = [commitIndex EXCEPT ![r] = Min2(@, Len(branch'[r]))]
    /\ UNCHANGED <<byzActions, auditIndex>>

\* True iff leader p is in a stable view
\* A view is stable when an audit quorum has the view's first batch
CheckViewStability(p) ==
    LET inView(batch) == batch.view=view[p] IN
    \E Q \in AQ: 
        \A q \in Q: 
            prepareQC'[p][q] >= SelectInSeq(branch[p], inView)

\* Leader p receiving votes from replica r
ReceiveVote(p, r) ==
    \* p must be the leader
    /\ leader[p]
    \* and the next message is a vote from the correct view
    /\ network[p][r] # <<>>
    /\ Head(network[p][r]).type = "Vote"
    /\ view[p] = Head(network[p][r]).view
    /\ prepareQC' = [prepareQC EXCEPT 
        ![p][r] = IF @ \leq Len(Head(network[p][r]).branch)
        THEN Len(Head(network[p][r]).branch)
        ELSE @]
    \* we remove the Vote message.
    /\ network' = [network EXCEPT ![p][r] = Tail(network[p][r])]
    \* if view is not already stable, check if it is now
    /\ viewStable' = [viewStable EXCEPT ![p] = 
            IF @ THEN @ ELSE CheckViewStability(p)]
    \* If view is stable, then the leader can update its commit indexes
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

\* Leader p sends AppendEntries to all replicas
SendEntries(p) ==
    \* p must be the leader
    /\ leader[p]
    \* and view must be stable
    /\ viewStable[p]
    /\ \E tx \in Txs:
        \* leader will not send an appendEntries to itself so update prepareQC here
        /\ prepareQC' = [prepareQC EXCEPT ![p][p] = Len(branch[p]) + 1]
        \* add the new batch to the branch
        /\ LET qc == MaxAuditQC(branch[p], prepareQC'[p]) IN
           branch' = [branch EXCEPT ![p] = Append(@, [
            view |-> view[p],
            \* for simplicity, each txn batch includes a single txn
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

\* Replica r times out
Timeout(r) ==
    /\ view' = [view EXCEPT ![r] = view[r] + 1]
    \* send a view change message to the new leader (even if it's itself)
    /\ network' = [network EXCEPT ![Leader(view'[r])][r] = Append(@, [
        type |-> "ViewChange",
        view |-> view'[r],
        branch |-> branch[r]])
        ]
    \* step down if replica was a leader
    /\ leader' = [leader EXCEPT ![r] = FALSE]
    /\ viewStable' = [viewStable EXCEPT ![r] = FALSE]
    \* reset prepareQCs, these are not used until the node is elected leader
    /\ prepareQC' = [prepareQC EXCEPT ![r] = [s \in R |-> 0]]
    /\ UNCHANGED <<branch, commitIndex, auditIndex, byzActions>>

\* The view of the highest auditQC in branch b, -1 if branch contains no qcs
HighestQCView(b) ==
    LET idx == HighestAuditQC(b) IN
    IF idx = 0 THEN -1 ELSE b[idx].view

\* True if branch b is valid branch choice from the set of branches bs.
\* Assumes that b \in bs
BranchChoiceRule(b,bs) ==
    \* if all branches are empty, then any b must be empty and a valid choice
    \/ \A b2 \in bs: b2 = <<>>
    \/ /\ b # <<>>
        \* b is valid if all other branches in bs are empty or b is from a higher view or
       /\ LET v1 == HighestQCView(b)
          IN \A b2 \in bs:
                \* b is valid if all other branches in bs are empty or...
                b # b2 /\ b2 # <<>>
                =>  LET v2 == HighestQCView(b2) IN
                    \* b is from a higher view or...
                    \/ v1 > v2
                    \* b is from the same view but at least as long
                    \/ /\ v1 = v2
                       /\ \/ Last(b).view > Last(b2).view
                          \/ /\ Last(b).view = Last(b2).view
                             /\ Len(b) >= Len(b2)

\* Replica r becomes leader
BecomeLeader(r) ==
    \* replica must be assigned the new view
    /\ r = Leader(view[r])
    \* an audit quorum must have voted for the replica
    /\ \E q \in AQ:
        /\ \A n \in q: 
            /\ network[r][n] # <<>>
            /\ Head(network[r][n]).type = "ViewChange"
            /\ view[r] = Head(network[r][n]).view
        /\ \E b1 \in {Head(network[r][n]).branch : n \in q}:
            \* Non-deterministically pick a branch from the set of branches in the quorum that satisfy the branch choice rule.
            /\ BranchChoiceRule(b1, {Head(network[r][n]).branch : n \in q})
            \* Leader adopts chosen branch and adds a new batch in the new view
            /\ branch' = [branch EXCEPT ![r] = Append(b1, [
                view |-> view[r],
                tx |-> <<>>,
                commitQC |-> {},
                auditQC |-> {},
                auditQCVotes |-> {}])]
            /\ prepareQC' = [prepareQC EXCEPT ![r][r] = Len(branch'[r])]
        \* Need to update network to remove the view change message and send a NewView message to all replicas
        /\ network' = [r1 \in R |-> [r2 \in R |-> 
            IF r1 = r /\ r2 \in q 
            THEN Tail(network[r1][r2]) 
            ELSE IF r1 # r /\ r2 = r 
                THEN Append(network[r1][r2], [ 
                    type |-> "NewView",
                    view |-> view[r],
                    branch |-> branch'[r]])
                ELSE network[r1][r2]]]
    \* replica becomes a leader
    /\ leader' = [leader EXCEPT ![r] = TRUE]
    \* leader updates its commit indexes
    \* Commit index may be decreased if there's been an byz attack
    /\ commitIndex' = [commitIndex EXCEPT 
        ![r] = Max2(Min2(@, Len(branch'[r])), HighestCommitQC(branch'[r]))]
    /\ UNCHANGED <<view, byzActions, auditIndex, viewStable>>

\* Replicas will discard messages from previous views or extra view changes messages
\* Note that replicas must always discard messages as the pairwise channels are ordered
\* so a replica may need to discard an out-of-date message to process a more recent one
DiscardMessages ==
    /\ \E s,r \in R:
            network' = [network EXCEPT ![r][s] = SelectSeq(@, 
                LAMBDA m: ~(m.view < view[r] \/ 
                    (m.view = view[r] /\ m.type = "ViewChange" /\ leader[r])))]
    /\ UNCHANGED <<view, branch, leader, prepareQC, commitIndex, auditIndex, byzActions, viewStable>>

----
\* BYZANTINE ACTIONS
\* Byzantine actions can only be taken by Byzantine replicas (BR) and if there are Byzantine actions left to take

\* A Byzantine replica might vote for a batch without actually appending it to its branch.
\* This Byzantine action currently has the same preconditions as AppendEntries
ByzOmitEntries(r, p) ==
    /\ r \in BR
    /\ byzActions < MaxByzActions
    /\ byzActions' = byzActions + 1
    \* there must be at least one message pending
    /\ network[r][p] # <<>>
    \* and the next message is an AppendEntries
    /\ Head(network[r][p]).type = "AppendEntries"
    \* the replica must be in the same view
    /\ view[r] = Head(network[r][p]).view
    \* the replica only appends one batch to its branch
    /\ branch[r] = Front(Head(network[r][p]).branch)
    \* we remove the AppendEntries message and reply with a Vote message.
    /\ network' = [network EXCEPT 
        ![r][p] = Tail(@),
        ![p][r] = Append(@,[
            type |-> "Vote",
            view |-> view[r],
            branch |-> Head(network[r][p]).branch
            ])
        ]
    /\ UNCHANGED <<leader, view, prepareQC, commitIndex, auditIndex, branch, viewStable>>

\* Given an append entries message, returns the same message with the txn changed to 1
ModifyAppendEntries(m) == [
    type |-> "AppendEntries",
    view |-> m.view,
    branch |-> SubSeq(m.branch,1,Len(m.branch)-1) \o
        <<[Last(m.branch) EXCEPT !.tx = <<1>>]>>
]


\* We allow a Byzantine leader to equivocate by changing the txn in an AppendEntries message
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

\* Next state relation
\* Note that the Byzantine actions are included here but can be disabled by setting MaxByzActions to 0 or BR to {}.
Next == 
    \/ DiscardMessages
    \/ \E r \in BR:
        \/ ByzLeaderEquivocate(r)
        \/ \E s \in R: \* Could be CR because we don't need byz replicas to receive messages from other byz replicas
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
    \* Only Timeout if there is no leader.
    /\ WF_vars(DiscardMessages)
    /\ \A r \in HR: WF_vars(TRUE \notin Range(leader) /\ Timeout(r))
    /\ \A r \in HR: WF_vars(BecomeLeader(r))
    /\ \A r \in HR: WF_vars(SendEntries(r))
    /\ \A r,s \in HR: WF_vars(ReceiveEntries(r,s))
    /\ \A r,s \in HR: WF_vars(ReceiveVote(r,s))
    /\ \A r,s \in HR: WF_vars(ReceiveNewView(r,s))
    \* Omit any Byzantine actions from the fairness condition.

Spec == 
    /\ Init
    /\ [][Next]_vars
    /\ Fairness

----
\* PROPERTIES

\* Correct replicas are either honest or Byzantine when no Byzantine actions have been taken yet
CR == IF byzActions = 0 THEN R ELSE HR

Committed(r) ==
    SubSeq(branch[r], 1, commitIndex[r])

\* The view of a batch is always greater than or equal to the view of the previous batch, i.e.,
\* the view of batches is (non-strictly) monotonically increasing.
ViewMonotonicInv ==
    \A r \in R :
        \A i \in 2..Len(branch[r]) :
            branch[r][i].view >= branch[r][i-1].view

\* Every view starts with a view stabilization batch. Moreover, view 0 is always stable.
\* Therefore, view 0 has no view stabilization batch.
ViewStabilizationInv ==
    \A r \in R :
        /\ \A i \in 1..Len(branch[r]) :
            /\ branch[r][i].tx = <<>> => branch[r][i].view # 0
            /\ i > 1 /\ branch[r][i].view > branch[r][i-1].view => branch[r][i].tx = <<>>

\* Ignoring view stabilization batches (modeled as empty txs), true iff the branch p is a prefix of branch b.
IsPrefixWithoutEmpty(p, b) ==
    \* p can be longer than b. Suppose b matches p as a prefix up to index i, but the suffix of p starting
    \* at i+1 contains only view stabilization batches. By adding the condition Len(p) <= Len(b), we
    \* ensure that such cases are not considered as p being a prefix of b. Instead, we require that b is at
    \* least as long as p, ensuring that b has a suffix distinct from p.
    \* Independently, this condition prevents out-of-bounds access when p is longer than b. For example, if
    \* b = <<>> (an empty sequence), attempting to access b[k] in the disjunct p[k] = b[k] would lead to an
    \* out-of-bounds access.
    /\ Len(p) <= Len(b)
    /\ \A k \in 1..Len(p):
          \/ p[k] = b[k]
          \/ p[k].tx = <<>>

\* If no Byzantine actions have been taken, then the committed branches of all replicas must be prefixes of each other
\* This, together with CommittedBranchAppendOnlyProp, is the classic CFT safety property
\* Note that if any nodes have been Byzantine, then this property is not guaranteed to hold on any node
\* BranchInv implies that the audited branches of replicas are prefixes too,
\* as IndexBoundsInv ensures that the auditIndex is always less than or equal to the commitIndex.
BranchInv ==
    byzActions = 0 =>
        \A i, j \in R :
            \/ IsPrefixWithoutEmpty(Committed(i),Committed(j)) 
            \/ IsPrefixWithoutEmpty(Committed(j),Committed(i))

Audited(r) ==
    SubSeq(branch[r], 1, auditIndex[r])

\* Variant of BranchInv for the audit index and correct replicas only
\* We make no assertions about the state of Byzantine replicas
AuditBranchInv ==
    \A i, j \in CR :
        \/ IsPrefix(Audited(i),Audited(j)) 
        \/ IsPrefix(Audited(j),Audited(i))

\* If no Byzantine actions have been taken, then each replica only appends to its committed branch
\* Note that this invariant allows empty blocks (sent at the start of a view) to be rolled back
CommittedBranchAppendOnlyProp ==
    [][byzActions = 0 => 
        \A i \in R :
        IsPrefixWithoutEmpty(Committed(i), Committed(i)')]_vars

\* All correct replicas only append to their audited branches
MonotonicAuditedIndexProp ==
    [][\A i \in CR :
        auditIndex[i] <= auditIndex'[i]]_vars

\* Each correct replica only appends to its audited branch
AuditedBranchAppendOnlyProp ==
    [][\A i \in CR :
        IsPrefix(Audited(i), Audited(i)')]_vars

\* At most one correct replica is leader in a view
OneLeaderPerViewInv ==
    \A v \in 0..Max(Range(view)), r \in CR :
        view[r] = v /\ leader[r]
        => \A s \in R \ {r} : view[s] = v => ~leader[s]

\* The commit and audit indexes are within bounds
\* The audit index is always less than or equal to the commit index
IndexBoundsInv ==
    \A r \in CR :
        /\ commitIndex[r] <= Len(branch[r])
        /\ auditIndex[r] <= commitIndex[r]

\* The branch of each replica is well formed
WellFormedBranchInv ==
    \A r \in CR : WellFormedBranch(branch[r])

====
