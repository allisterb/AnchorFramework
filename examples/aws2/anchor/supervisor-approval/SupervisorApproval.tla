---------------------------- MODULE SupervisorApproval ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Amounts == {499, 500, 2500, 2501}
Booleans == {TRUE, FALSE}
ChargeIds == {1, 2}
Gaps == {60, 1800, 1801}

VARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap

Init ==
    /\ amount \in Amounts
    /\ has_approval \in Booleans
    /\ approved \in Booleans
    /\ approval_charge \in ChargeIds
    /\ refund_charge \in ChargeIds
    /\ gap \in Gaps

Next == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>

Spec == Init /\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>

ApprovalEv ==
    Ev("request_approval", "response",
       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],
       [approved |-> Bool(approved), verified |-> Bool(TRUE)],
       100)

RefundEv ==
    Ev("issue_refund", DecisionKind,
       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],
       NoFields,
       IF has_approval THEN 100 + gap ELSE 100)

Session ==
    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>

DecisionIndex ==
    IF has_approval THEN 2 ELSE 1

RefundAllowed ==
    D!Decide(Session, Policies, DecisionIndex, AllValues)

ValidApproval(h, app, ac, rc, g) ==
    /\ h
    /\ app
    /\ ac = rc
    /\ g <= 1800

Over500RequiresApproval ==
    (amount > 500 /\ ~ValidApproval(has_approval, approved, approval_charge, refund_charge, gap)) => ~RefundAllowed

ApprovedRefundIsAllowed ==
    (amount = 2500 /\ has_approval /\ approved /\ approval_charge = 1 /\ refund_charge = 1 /\ gap = 60) => RefundAllowed

SmallRefundWithoutApprovalIsAllowed ==
    (amount = 500 /\ ~has_approval /\ refund_charge = 1 /\ gap = 60 /\ approval_charge = 1 /\ ~approved) => RefundAllowed

=============================================================================
