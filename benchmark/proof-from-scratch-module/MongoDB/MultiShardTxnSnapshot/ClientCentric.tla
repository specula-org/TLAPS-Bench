--------------------------- MODULE ClientCentric ---------------------------
EXTENDS Naturals, Sequences, FiniteSets, Util
VARIABLES Keys, Values

r(k,v) == [op |-> "read",  key |-> k, value |-> v]
w(k,v) == [op |-> "write", key |-> k, value |-> v]

executionStates(execution) == [ i \in 1..Len(execution) |-> execution[i].parentState ]

parentState(execution, transaction) == 
  LET ind == CHOOSE i \in 1..Len(execution): execution[i].transaction = transaction
  IN execution[ind].parentState

earlierInTransaction(transaction, op1, op2) == Index(transaction, op1) < Index(transaction, op2)

beforeOrEqualInExecution(execution, state1, state2) == 
  LET states == executionStates(execution)
  IN  Index(states, state1) <= Index(states, state2)

ReadStates(execution, operation, transaction) == 
  LET Se == SeqToSet(executionStates(execution))
      sp == parentState(execution, transaction)
  IN { s \in Se:
        /\ beforeOrEqualInExecution(execution, s, sp) 
        /\ \/ s[operation.key] = operation.value 
           \/ \E write \in SeqToSet(transaction): 
              /\ write.op = "write" /\ write.key = operation.key /\ write.value = operation.value
              /\ earlierInTransaction(transaction, write, operation) 

           \/ operation.op = "write"
     }

Complete(execution, transaction, state) == 
  LET setOfAllReadStatesOfOperation(transactionOperations) ==
        { ReadStates(execution, operation, transaction) : operation \in SeqToSet(transactionOperations) }
     
      readStatesForEmptyTransaction == { s \in SeqToSet(executionStates(execution)) : beforeOrEqualInExecution(execution, s, parentState(execution, transaction)) }
  IN state \in INTERSECTION(setOfAllReadStatesOfOperation(transaction) \union { readStatesForEmptyTransaction } )

WriteSet(transaction) == 
  LET writes == { operation \in SeqToSet(transaction) : operation.op = "write" } 
  IN { operation.key : operation \in writes } 

NoConf(execution, transaction, state) == 
  LET Sp == parentState(execution, transaction)
      delta == { key \in DOMAIN Sp : Sp[key] /= state[key] }
  IN delta \intersect WriteSet(transaction) = {}

effects(state, transaction) == 
       ReduceSeq(LAMBDA o, newState: IF o.op = "write" THEN [newState EXCEPT ![o.key] = o.value] ELSE newState, transaction, state)

executions(initialState, transactions) == 
  
  LET orderings == PermSeqs(transactions)

      accummulator == [ execution |-> <<>>, nextState |-> initialState ]
  IN { LET executionAcc == ReduceSeq(
                            
                            LAMBDA t, acc: [ execution |-> Append(acc.execution, [parentState |-> acc.nextState, transaction |-> t])
                            
                                           , nextState |-> effects(acc.nextState,t) 
                            ],
                            ordering, accummulator)
    
       IN executionAcc.execution
     : ordering \in orderings }

satisfyIsolationLevel(initialState, transactions, commitTest(_,_)) ==
  \E execution \in executions(initialState, transactions): \A transaction \in transactions:
    
    commitTest(transaction, execution)

CT_SI(transaction, execution) == 
    \E state \in SeqToSet(executionStates(execution)):
        /\ Complete(execution, transaction, state) 
        /\ NoConf(execution, transaction, state)

SnapshotIsolation(initialState, transactions) == satisfyIsolationLevel(initialState, transactions, CT_SI)

=============================================================================
