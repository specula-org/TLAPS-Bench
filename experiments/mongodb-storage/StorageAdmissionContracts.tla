--------------------- MODULE StorageAdmissionContracts ---------------------
EXTENDS StorageReadContracts

AcceptedMutation(n,t,k) ==
  /\ (\E v \in Values : TransactionWrite(n,t,k,v,"false"))
       \/ TransactionRemove(n,t,k)
  /\ txnStatus'[n][t] = STATUS_OK

THEOREM SuccessfulMutationHasNoConflict ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys,
         StatusShape, AcceptedMutation(n,t,k)
  PROVE /\ t \in ActiveTransactions(n)
        /\ ~WriteConflictExists(n,t,k)
BY SMT DEF StatusShape, AcceptedMutation, TransactionWrite, TransactionRemove,
           STATUS_OK, STATUS_ROLLBACK, STATUS_NOTFOUND

AdmissionContract ==
  \A n \in Node, t \in MTxId, k \in Keys :
    AcceptedMutation(n,t,k) =>
      /\ \A other \in ActiveTransactions(n) \ {t} :
           k \notin mtxnSnapshots[n][other].writeSet
      /\ \A i \in DOMAIN mlog[n] :
           (/\ "data" \in DOMAIN mlog[n][i]
            /\ mlog[n][i].tid \in MTxId \ {t}
            /\ mlog[n][i].ts > mtxnSnapshots[n][t].ts)
             => k \notin DOMAIN mlog[n][i].data

THEOREM AdmissionStep == StatusShape => AdmissionContract
BY SMT, SuccessfulMutationHasNoConflict
   DEF AdmissionContract, WriteConflictExists, ActiveTransactions

THEOREM FullNextAdmission == Spec => [][AdmissionContract]_vars
BY FullNextStatusShape, AdmissionStep, PTL
=============================================================================
