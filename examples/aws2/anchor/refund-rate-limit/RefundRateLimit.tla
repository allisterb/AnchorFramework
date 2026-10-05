---------------------------- MODULE RefundRateLimit ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Hour == 3600

RefundReq(t, acc) ==
    Ev("issue_refund", "request",
       [account |-> Num(acc), amount |-> Num(499), systemNowTime |-> Num(32400000)],
       NoFields, t)

Trace(priorCount, priorAcc, targetAcc, gap) ==
    IF priorCount = 0 THEN
        << RefundReq(100 + gap, targetAcc) >>
    ELSE IF priorCount = 1 THEN
        << RefundReq(100, priorAcc),
           RefundReq(100 + gap, targetAcc) >>
    ELSE IF priorCount = 2 THEN
        << RefundReq(100, priorAcc),
           RefundReq(110, priorAcc),
           RefundReq(100 + gap, targetAcc) >>
    ELSE
        << RefundReq(100, priorAcc),
           RefundReq(110, priorAcc),
           RefundReq(120, priorAcc),
           RefundReq(100 + gap, targetAcc) >>

DecisionIndex(priorCount) ==
    IF priorCount = 0 THEN 1
    ELSE IF priorCount = 1 THEN 2
    ELSE IF priorCount = 2 THEN 3
    ELSE 4

RefundAllowed(priorCount, priorAcc, targetAcc, gap) ==
    D!Decide(Trace(priorCount, priorAcc, targetAcc, gap), Policies, DecisionIndex(priorCount), AllValues)

VARIABLES priorCount, priorAcc, targetAcc, gap

PriorCounts == {0, 1, 2, 3}
Accounts    == {1, 2}
Gaps        == {600, 1800, Hour, Hour + 1, 2 * Hour}

Init ==
    /\ priorCount \in PriorCounts
    /\ priorAcc \in Accounts
    /\ targetAcc \in Accounts
    /\ gap \in Gaps

Next == UNCHANGED <<priorCount, priorAcc, targetAcc, gap>>

Spec == Init /\ [][Next]_<<priorCount, priorAcc, targetAcc, gap>>

FourthRefundWithinHourRefused ==
    (priorCount = 3 /\ priorAcc = targetAcc /\ gap <= Hour)
        => ~RefundAllowed(priorCount, priorAcc, targetAcc, gap)

CompliantRefundAllowed ==
    (priorCount = 0 /\ priorAcc = 1 /\ targetAcc = 1 /\ gap = 600)
        => RefundAllowed(priorCount, priorAcc, targetAcc, gap)

=============================================================================
