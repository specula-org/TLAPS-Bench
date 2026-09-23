---- MODULE SailfishNoVote ----
EXTENDS SailfishReplay
CONSTANT HasCertificate
PreGST == 6
Prefix == <<[node |-> b, rnd |-> 1, parents |-> {Genesis}],
            [node |-> c, rnd |-> 1, parents |-> {Genesis}],
            [node |-> d, rnd |-> 1, parents |-> {Genesis}],
            [node |-> b, rnd |-> 2, parents |-> {<<b, 1>>, <<c, 1>>, <<d, 1>>}]>>
ExtraVote == <<[node |-> c, rnd |-> 2, parents |-> {<<b, 1>>, <<c, 1>>, <<d, 1>>}]>>
Proposal == <<[node |-> d, rnd |-> 2, parents |-> {<<b, 1>>, <<c, 1>>, <<d, 1>>}]>>
CertificateSchedule == Prefix \o (IF HasCertificate THEN ExtraVote ELSE <<>>) \o Proposal
====
