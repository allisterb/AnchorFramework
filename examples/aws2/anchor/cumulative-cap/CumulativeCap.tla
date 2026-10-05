---------------------------- MODULE CumulativeCap ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Hour == 3600
Window == 12 * Hour

PriorAmounts == {20000, 30000, 40000}
CurrentAmounts == {15000, 25000, 55000}
Gaps == {1 * Hour, Window, Window + 1, 24 * Hour}

VARIABLES priorAmount, currentAmount, gap

Init ==
  /\ priorAmount \in PriorAmounts
  /\ currentAmount \in CurrentAmounts
  /\ gap \in Gaps

Next == UNCHANGED <<priorAmount, currentAmount, gap>>
Spec == Init /\ [][Next]_<<priorAmount, currentAmount, gap>>

Verify(t) == Ev("verify_identity", "response", [account |-> Num(1)], [verified |-> Bool(TRUE)], t)
Transfer(amt, t) == Ev("initiate_transfer", "request", [account |-> Num(1), amount |-> Num(amt)], NoFields, t)

Session == <<
  Verify(1),
  Transfer(priorAmount, 2),
  Verify(1 + gap),
  Transfer(currentAmount, 2 + gap)
>>

TransferAllowed == D!Decide(Session, Policies, 4, AllValues)

ExceedingCapWithin12hIsRefused ==
  (gap <= Window /\ priorAmount + currentAmount > 50000) => ~TransferAllowed

ExceedingCapAfter12hIsRefused ==
  (gap > Window /\ currentAmount > 50000) => ~TransferAllowed

CompliantSessionUnderCapAllowed ==
  (priorAmount = 20000 /\ currentAmount = 15000 /\ gap = 1 * Hour) => TransferAllowed

CompliantSessionAfter12hAllowed ==
  (priorAmount = 30000 /\ currentAmount = 25000 /\ gap = Window + 1) => TransferAllowed

=============================================================================
