---------------------------- MODULE RefundRateLimit ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Verify == Ev("verify_identity", "response", NoFields, [verified |-> Bool(TRUE)], 1)
Refund(acct, t) == Ev("issue_refund", "request", [account |-> Num(acct), amount |-> Num(500), charge_id |-> Num(1), systemNowTime |-> Num(32400000)], NoFields, t)

Session(pCount, acct, g) ==
    IF pCount = 2
    THEN << Verify, Refund(1, 10), Refund(1, 20), Refund(acct, 10 + g) >>
    ELSE << Verify, Refund(1, 10), Refund(1, 20), Refund(1, 30), Refund(acct, 10 + g) >>

RefundAllowed(pCount, acct, g) ==
    D!Decide(Session(pCount, acct, g), Policies, pCount + 2, AllValues)

VARIABLES priorCount, targetAccount, gap

Init ==
    /\ priorCount    \in {2, 3}
    /\ targetAccount \in {1, 2}
    /\ gap           \in {3600, 3601}

Next == UNCHANGED <<priorCount, targetAccount, gap>>
Spec == Init /\ [][Next]_<<priorCount, targetAccount, gap>>

\* The agent might attempt no more than three refunds against the same account within one hour (3600s).
\* If there are already 3 refunds on the same account within 1 hour (gap <= 3600s), the 4th refund is refused.
ExceedingRateLimitRefused ==
    (priorCount = 3 /\ targetAccount = 1 /\ gap <= 3600) => ~RefundAllowed(priorCount, targetAccount, gap)

\* At most 3 refunds on the same account within 1 hour is allowed when prerequisites are met.
CompliantRefundAllowed ==
    (priorCount = 2 /\ targetAccount = 1 /\ gap <= 3600) => RefundAllowed(priorCount, targetAccount, gap)

=============================================================================