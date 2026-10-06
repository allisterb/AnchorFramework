---------------------------- MODULE IdentityVerification ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Minute == 60
FifteenMinutes == 15 * Minute

Accounts == {1, 2}
Gaps == {60, FifteenMinutes, FifteenMinutes + 1, 1800}

VARIABLES hasVerification, vAccount, tAccount, verified, gap

Init ==
  /\ hasVerification \in {TRUE, FALSE}
  /\ vAccount \in Accounts
  /\ tAccount \in Accounts
  /\ verified \in {TRUE, FALSE}
  /\ gap \in Gaps

Next == UNCHANGED <<hasVerification, vAccount, tAccount, verified, gap>>

Spec == Init /\ [][Next]_<<hasVerification, vAccount, tAccount, verified, gap>>

Verify(acc, ver, t) ==
  Ev("verify_identity", "response", [account |-> Num(acc)], [verified |-> Bool(ver)], t)

Transfer(acc, t) ==
  Ev("initiate_transfer", "request", [account |-> Num(acc), amount |-> Num(500)], NoFields, t)

Session ==
  IF hasVerification
  THEN << Verify(vAccount, verified, 1), Transfer(tAccount, 1 + gap) >>
  ELSE << Transfer(tAccount, 1) >>

DecisionIndex == IF hasVerification THEN 2 ELSE 1

TransferAllowed == D!Decide(Session, Policies, DecisionIndex, AllValues)

CompliantTransferIsAllowed ==
  (hasVerification /\ verified /\ vAccount = 1 /\ tAccount = 1 /\ gap = 60) => TransferAllowed

NoVerificationIsRefused ==
  (~hasVerification) => ~TransferAllowed

FailedVerificationIsRefused ==
  (hasVerification /\ ~verified) => ~TransferAllowed

MismatchedAccountIsRefused ==
  (hasVerification /\ vAccount # tAccount) => ~TransferAllowed

ExpiredVerificationIsRefused ==
  (hasVerification /\ gap > FifteenMinutes) => ~TransferAllowed

=============================================================================