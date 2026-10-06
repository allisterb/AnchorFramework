---------------------------- MODULE CumulativeCap ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Hour == 3600
Cap == 50000
Window == 12 * Hour

PrevAmounts == {30000}
CurrentAmounts == {20000, 20001, 50000, 50001}
Gaps == {300, Window, Window + 1}

VARIABLES prevAmount, currentAmount, gap

Init ==
  /\ prevAmount \in PrevAmounts
  /\ currentAmount \in CurrentAmounts
  /\ gap \in Gaps

Next == UNCHANGED <<prevAmount, currentAmount, gap>>
Spec == Init /\ [][Next]_<<prevAmount, currentAmount, gap>>

Session == <<
  Ev("verify_identity", "response", [account |-> Num(1)], [verified |-> Bool(TRUE)], 100),
  Ev("initiate_transfer", "request", [amount |-> Num(prevAmount), account |-> Num(1)], NoFields, 100),
  Ev("verify_identity", "response", [account |-> Num(1)], [verified |-> Bool(TRUE)], 100 + gap),
  Ev("initiate_transfer", "request", [amount |-> Num(currentAmount), account |-> Num(1)], NoFields, 100 + gap)
>>

TransferAllowed == D!Decide(Session, Policies, 4, AllValues)

ExceedingCapIsBlocked ==
  ((gap <= Window /\ prevAmount + currentAmount > Cap) \/ (gap > Window /\ currentAmount > Cap)) => ~TransferAllowed

CompliantTransferIsAllowed ==
  (gap = 300 /\ prevAmount = 30000 /\ currentAmount = 20000) => TransferAllowed

=============================================================================