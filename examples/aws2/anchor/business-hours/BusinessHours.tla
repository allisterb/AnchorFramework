---------------------------- MODULE BusinessHours ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

BusinessHoursMin == 32400000
BusinessHoursMax == 61200000
MaxAmount == 2500

accountValues == {1, 2}
amountValues == {499, 500, 2500, 2501}
charge_idValues == {1, 2}
systemNowTimeValues == {32399999, 32400000, 61200000, 61200001}

Requests == {[account |-> account, amount |-> amount, charge_id |-> charge_id, systemNowTime |-> systemNowTime] :
  account \in accountValues, amount \in amountValues, charge_id \in charge_idValues, systemNowTime \in systemNowTimeValues}

RefundAllowed(r) ==
  D!Decide(
    <<Request("issue_refund", [
        account |-> Num(r.account),
        amount |-> Num(r.amount),
        charge_id |-> Num(r.charge_id),
        systemNowTime |-> Num(r.systemNowTime)
      ])>>,
    Policies,
    1,
    AllValues
  )

VARIABLE req

Init == req \in Requests
Next == UNCHANGED req
Spec == Init /\ [][Next]_req

OutsideBusinessHoursRefused ==
  (req.systemNowTime < BusinessHoursMin \/ req.systemNowTime > BusinessHoursMax) => ~RefundAllowed(req)

OverMaxAmountRefused ==
  (req.amount > MaxAmount) => ~RefundAllowed(req)

CompliantRefundAllowed ==
  (req.amount = 500 /\ req.systemNowTime = BusinessHoursMin /\ req.account = 1 /\ req.charge_id = 1) => RefundAllowed(req)

=============================================================================
