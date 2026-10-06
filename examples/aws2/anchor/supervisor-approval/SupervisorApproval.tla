---------------------------- MODULE SupervisorApproval ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Approval(charge, appr, t) ==
    Ev("request_approval", "response",
       [charge_id |-> Num(charge)],
       [approved |-> Bool(appr)],
       t)

Refund(charge, amt, t) ==
    Ev("issue_refund", "request",
       [charge_id |-> Num(charge),
        amount |-> Num(amt),
        systemNowTime |-> Num(32400000)],
       NoFields,
       t)

VARIABLES hasApproval, approvalCharge, approved, gap, refundCharge, amount

Init ==
    /\ hasApproval    \in {TRUE, FALSE}
    /\ approvalCharge \in {1, 2}
    /\ approved       \in {TRUE, FALSE}
    /\ gap            \in {60, 1800, 1801}
    /\ refundCharge   \in {1, 2}
    /\ amount         \in {499, 500, 501, 1000}

Next == UNCHANGED <<hasApproval, approvalCharge, approved, gap, refundCharge, amount>>
Spec == Init /\ [][Next]_<<hasApproval, approvalCharge, approved, gap, refundCharge, amount>>

Session ==
    IF hasApproval
    THEN << Approval(approvalCharge, approved, 1000), Refund(refundCharge, amount, 1000 + gap) >>
    ELSE << Refund(refundCharge, amount, 1000) >>

DecisionIndex == IF hasApproval THEN 2 ELSE 1

RefundAllowed == D!Decide(Session, Policies, DecisionIndex, AllValues)

Over500WithoutApprovalRefused ==
    (amount > 500 /\ ~(hasApproval /\ approved /\ approvalCharge = refundCharge /\ gap <= 1800)) => ~RefundAllowed

CompliantApprovalAllowed ==
    (hasApproval /\ approved /\ approvalCharge = 1 /\ refundCharge = 1 /\ gap = 60 /\ amount = 501) => RefundAllowed

CompliantUnder500Allowed ==
    (~hasApproval /\ refundCharge = 1 /\ amount = 500 /\ gap = 60 /\ approvalCharge = 1 /\ approved = FALSE) => RefundAllowed

=============================================================================
