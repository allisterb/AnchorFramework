---------------------------- MODULE BusinessHours ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Approval(t) == Ev("request_approval", "response", [charge_id |-> Num(1)], [approved |-> Bool(TRUE)], t)
Refund(t, amt, nowTime) == Ev("issue_refund", "request", [charge_id |-> Num(1), amount |-> Num(amt), systemNowTime |-> Num(nowTime), account |-> Num(1)], NoFields, t)

Session(amt, nowTime) == << Approval(1), Refund(2, amt, nowTime) >>
RefundAllowed(amt, nowTime) == D!Decide(Session(amt, nowTime), Policies, 2, AllValues)

BusinessHoursStart == 32400000
BusinessHoursEnd   == 61200000
MaxRefundAmount    == 2500

Amounts == {500, MaxRefundAmount, MaxRefundAmount + 1}
Times   == {BusinessHoursStart - 1, BusinessHoursStart, 40000000, BusinessHoursEnd, BusinessHoursEnd + 1}

VARIABLES amount, nowTime

Init ==
    /\ amount \in Amounts
    /\ nowTime \in Times

Next == UNCHANGED <<amount, nowTime>>

Spec == Init /\ [][Next]_<<amount, nowTime>>

OutsideBusinessHoursRefused ==
    (nowTime < BusinessHoursStart \/ nowTime > BusinessHoursEnd) => ~RefundAllowed(amount, nowTime)

OverAmountLimitRefused ==
    (amount > MaxRefundAmount) => ~RefundAllowed(amount, nowTime)

CompliantRefundAllowed ==
    (amount = MaxRefundAmount /\ nowTime = BusinessHoursStart) => RefundAllowed(amount, nowTime)

=============================================================================
