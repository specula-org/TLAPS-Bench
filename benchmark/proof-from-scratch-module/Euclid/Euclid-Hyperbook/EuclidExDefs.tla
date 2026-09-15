------------------------------ MODULE EuclidExDefs ------------------------------
EXTENDS EuclidExModel

PartialCorrectness ==
    (pc = "Done") => (x = y) /\ (x = GCD(M, N))

=============================================================================

