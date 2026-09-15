----------------------------- MODULE SumAndMaxDefs -----------------------------
EXTENDS SumAndMaxModel

Correctness == pc = "Done" => sum =< N*max

=============================================================================
