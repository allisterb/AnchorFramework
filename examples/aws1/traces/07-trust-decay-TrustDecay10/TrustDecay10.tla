---------------------------- MODULE TrustDecay10 ----------------------------
\* What `07-trust-decay.dw` is SUPPOSED to mean under a TIGHTER deadline than it states.
\* published it, and checked against the same records the built-in questions are checked against.
\*
\*   "After 15 minutes without advisor interaction, the agent loses access to write operations."
\*
\* THE BUILT-IN QUESTIONS CANNOT EVALUATE THAT SENTENCE, and they say so cheerfully: the derived
\* run on this file reports "every rule is load-bearing within 3 attempts". True, and no comfort
\* at all -- a permit that fires is a permit that fires, whichever way round its condition is.
\*
\* THIS CLAIM IS TEMPORAL, so it is not the one-request shape the skeleton offers. A session is
\* built by hand, with times chosen in SECONDS, because the evaluator compares an event's time
\* against the window width directly. The built-in exploration walks sessions one second apart,
\* so a 15-minute window can never age out there; only a trace like the one below can put a
\* decision on the far side of it.
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

(***************************************************************************)
(* THE SESSIONS THIS CLAIM IS ABOUT.                                       *)
(*                                                                         *)
(* Two events: the advisor interacts, and some time later the agent tries  *)
(* to trade. `Gap` is how long it waited, in seconds. That single number   *)
(* is the whole experiment.                                                *)
(***************************************************************************)
Interaction(t) == Ev("interact_advisor", "response", NoFields, NoFields, t)
Trade(t)       == Ev("execute_trade", DecisionKind, NoFields, NoFields, t)

Session(gap) == << Interaction(1), Trade(1 + gap) >>

\* The decision for the trade -- index 2, the second event in that session.
TradeAllowed(gap) == D!Decide(Session(gap), Policies, 2, AllValues)

\* Seconds, stated rather than computed, so that the numbers in the claims below are the numbers
\* in the sentences they come from.
Minute == 60

(***************************************************************************)
(* GAPS TO TRY, named here rather than derived.                            *)
(*                                                                         *)
(* PolicyUnderTest deliberately offers no `Inputs` and no domain of times: *)
(* a space derived from the policy's own literals would contain only the   *)
(* windows it mentions, and a claim about "ten minutes" would then range   *)
(* over nothing and pass having looked at nothing. Naming them is three    *)
(* lines and it is what makes the claim real.                              *)
(***************************************************************************)
Gaps == {1, 5 * Minute, 10 * Minute, 14 * Minute, 16 * Minute, 30 * Minute}

VARIABLE gap
Init == gap \in Gaps
Next == UNCHANGED gap
Spec == Init /\ [][Next]_gap

(***************************************************************************)
(* THE CLAIM, alone.                                                       *)
(*                                                                         *)
(* Its own module because TLC stops at the FIRST violated invariant: asked *)
(* beside the article's own 15-minute claims, this one never gets reported *)
(* on at all, and "no verdict" is easy to misread as "it held".            *)
(*                                                                         *)
(* "After 10 minutes without advisor interaction, the agent loses access   *)
(*  to write operations." -- a deadline TIGHTER than the policy states.    *)
(***************************************************************************)
LosesWriteAfter10m ==
    (gap > 10 * Minute) => ~TradeAllowed(gap)

=============================================================================
