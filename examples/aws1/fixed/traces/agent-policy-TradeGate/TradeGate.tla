---------------------------- MODULE TradeGate ----------------------------
\* What `agent-policy.dw` is SUPPOSED to mean -- the article's trade protections, together.
\*
\* The first `.dw` named in this header is the policy the module is about, which is the convention
\* `anchor auto` reads to pair them and which the generated skeleton already emits. A module that
\* names none is reported as unpaired rather than guessed at.
\*
\* Two of its policies guard `execute_trade`, and each is introduced as a distinct protection:
\*
\*   output-to-input integrity   the profile traded against must be the one this trajectory
\*                               loaded -- "prevents an attacker from using prompt injection to
\*                               steer the agent to trade against a different client's portfolio"
\*   data freshness              a price within the last 30 seconds -- "the agent cannot act on
\*                               stale quotes"
\*
\* Read as a list of requirements those are a conjunction. Written as two `permit` rules on the
\* same action they are ALTERNATIVES, because Cedar permits by positive match: either rule firing
\* is enough. This module states the conjunction and asks whether the policy set enforces it.
\*
\* THE DERIVED QUESTIONS CANNOT ASK THIS. Run them on `agent-policy.dw` and every rule is live,
\* including both of these -- they fire, they are not redundant, nothing is dead. "Every rule is
\* load-bearing" is true of a policy set whose rules each independently open the door.
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

\* The profile the trade names, and the one the profile load carried. Equal here, so the join in
\* the integrity policy is satisfied whenever the load is present at all -- the claim under test
\* is about which PREREQUISITES are needed, not about the join, which has its own policy.
Profile == [profile_id |-> Num(1)]

Loaded(t) == Ev("get_client_profile", "response", Profile, NoFields, t)
Priced(t) == Ev("get_market_price", "response", NoFields, NoFields, t)
Trade(t)  == Ev("execute_trade", DecisionKind, Profile, NoFields, t)

(***************************************************************************)
(* THE SESSIONS. Which prerequisites happened, before a trade at t = 40.   *)
(*                                                                         *)
(* 40 seconds, chosen so the two windows DISAGREE: a price at t = 1 is     *)
(* outside the 30-second freshness window, while a profile load at t = 1   *)
(* is comfortably inside the 24-hour one. Any time inside both would make  *)
(* "stale" untestable, and the whole point of the freshness policy is what *)
(* happens outside its window.                                            *)
(***************************************************************************)
Fresh == 30

Prereqs == {"both", "profileOnly", "freshPriceOnly", "stalePriceOnly", "neither"}

Session(w) ==
    CASE w = "both"           -> << Loaded(1), Priced(40 - Fresh + 1), Trade(40) >>
      [] w = "profileOnly"    -> << Loaded(1), Trade(40) >>
      [] w = "freshPriceOnly" -> << Priced(40 - Fresh + 1), Trade(40) >>
      [] w = "stalePriceOnly" -> << Priced(1), Trade(40) >>
      [] OTHER                -> << Trade(40) >>

\* The decision for the trade, which is always the last event of its session.
Allowed(w) == D!Decide(Session(w), Policies, Len(Session(w)), AllValues)

VARIABLE prereq
Init == prereq \in Prereqs
Next == UNCHANGED prereq
Spec == Init /\ [][Next]_prereq

(***************************************************************************)
(* THE CLAIMS.                                                             *)
(***************************************************************************)

\* The protections, read the way the article's prose reads: a trade needs BOTH.
RequiresBothChecks ==
    Allowed(prereq) => (prereq = "both")

\* Each half separately, so a failure says WHICH protection is optional rather than that one is.
ProfileAloneIsNotEnough ==
    (prereq = "profileOnly") => ~Allowed(prereq)

FreshPriceAloneIsNotEnough ==
    (prereq = "freshPriceOnly") => ~Allowed(prereq)

\* The one claim that should hold on any reading: with neither prerequisite, no trade.
NothingAllowsNoTrade ==
    (prereq = "neither") => ~Allowed(prereq)

\* And the positive direction -- the policy set is not so tight that the intended path is shut.
BothIsAllowed ==
    (prereq = "both") => Allowed(prereq)

=============================================================================
