---------------------------- MODULE IdentityVerification ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Minute == 60

VARIABLES hasVerifyEvent, isVerified, verifiedAccount, transferAccount, gap

Init ==
  /\ hasVerifyEvent \in {TRUE, FALSE}
  /\ isVerified \in {TRUE, FALSE}
  /\ verifiedAccount \in {1, 2}
  /\ transferAccount \in {1, 2}
  /\ gap \in {60, 15 * Minute, 15 * Minute + 1, 30 * Minute}

Next == UNCHANGED <<hasVerifyEvent, isVerified, verifiedAccount, transferAccount, gap>>

Spec == Init /\ [][Next]_<<hasVerifyEvent, isVerified, verifiedAccount, transferAccount, gap>>

VerifyEv ==
  Ev("verify_identity", "response", [account |-> Num(verifiedAccount)], [verified |-> Bool(isVerified)], 1)

TransferEv ==
  Ev("initiate_transfer", "request", [account |-> Num(transferAccount), amount |-> Num(499), systemNowTime |-> Num(32400000)], NoFields, 1 + gap)

Session ==
  IF hasVerifyEvent
  THEN <<VerifyEv, TransferEv>>
  ELSE <<TransferEv>>

DecideIndex == IF hasVerifyEvent THEN 2 ELSE 1

TransferAllowed == D!Decide(Session, Policies, DecideIndex, AllValues)

CompliantTransferAllowed ==
  (hasVerifyEvent /\ isVerified /\ verifiedAccount = 1 /\ transferAccount = 1 /\ gap = 60) => TransferAllowed

UnverifiedTransferRefused ==
  (~hasVerifyEvent \/ ~isVerified \/ (verifiedAccount # transferAccount) \/ (gap > 15 * Minute)) => ~TransferAllowed

=============================================================================