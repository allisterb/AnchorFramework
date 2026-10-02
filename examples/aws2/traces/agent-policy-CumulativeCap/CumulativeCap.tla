---------------------------- MODULE CumulativeCap ----------------------------
\* What `agent-policy.dw` is SUPPOSED to mean, in the article's own words:
\*
\*   "Block a transfer if the total amount TRANSFERRED in the past 12 hours would exceed $50,000."
\*
\* The word that carries the claim is *transferred*. A transfer that was refused moved no money, so
\* it cannot have contributed to a total of what was transferred -- and the budget it did not spend
\* must still be there.
\*
\* THE POLICY SUMS `::request`, which is the ATTEMPT rather than the transfer. Under AgentCore's
\* own convention the attempt is recorded whatever the outcome, and the outcome follows as
\* `::response` when the action completed or `::error` when it was denied. So a refused attempt
\* sits in the history looking exactly like a completed one to this rule.
\*
\* THE DERIVED QUESTIONS CANNOT ASK THIS. Run them on the policy set and the rule is live: it
\* fires, it is not redundant, nothing is dead. "Live" is true of a rule that charges the budget
\* for money that never moved.
\*
\* Contrast policy 4 beside it, which is the same shape and is CORRECT -- because its requirement
\* says the agent "might ATTEMPT no more than three refunds", and `::request` is the attempt. The
\* defect here is the event kind, not the shape, and the pair is what shows it.
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

(***************************************************************************)
(* THE SESSIONS. One account, one identity verification to open the permit, *)
(* and then either a clean small transfer or the same transfer after an     *)
(* oversized attempt has been REFUSED.                                      *)
(*                                                                         *)
(* $60,000 is over the cap on its own, so the attempt at t=2 is denied and  *)
(* AgentCore records the `::error` at t=3. No money moved.                  *)
(***************************************************************************)
Account  == [account |-> Str("a1")]
Verified == [verified |-> Bool(TRUE)]

Verify(t)        == Ev("verify_identity", "response", Account, Verified, t)
Transfer(amt, t) == Ev("initiate_transfer", "request",
                       [account |-> Str("a1"), amount |-> Num(amt)], NoFields, t)
Refused(amt, t)  == Ev("initiate_transfer", "error",
                       [account |-> Str("a1"), amount |-> Num(amt)], NoFields, t)

Scenarios == {"clean", "afterRefused"}

Session(s) ==
    CASE s = "clean" -> << Verify(1), Transfer(1, 2) >>
      [] OTHER       -> << Verify(1), Transfer(60000, 2), Refused(60000, 3), Transfer(1, 4) >>

\* The decision for the LAST event of each session -- the small $1 transfer, both times.
Allowed(s) == D!Decide(Session(s), Policies, Len(Session(s)), AllValues)

VARIABLE scenario
Init == scenario \in Scenarios
Next == UNCHANGED scenario
Spec == Init /\ [][Next]_scenario

(***************************************************************************)
(* THE CLAIM.                                                              *)
(***************************************************************************)

\* A $1 transfer is permitted in both sessions. The refused $60,000 moved no money, so the
\* twelve-hour total of what was TRANSFERRED is $0 either way.
ARefusedAttemptDoesNotConsumeTheBudget ==
    Allowed(scenario)

=============================================================================
