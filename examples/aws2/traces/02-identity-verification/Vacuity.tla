(***************************************************************************)
(* VACUITY, for an arbitrary Dogwood policy file.                          *)
(*                                                                         *)
(* The question: can permit number `Target` ever actually grant anything?  *)
(* A permit that no session can make fire is not a weak control, it is     *)
(* ZERO control, and nothing about its text says so. It parses, it         *)
(* validates, it is satisfiable in isolation, and it never authorizes a    *)
(* single request. That is the cheapest useful question to ask about a     *)
(* session-aware policy, and AWS's own material says their analysis tools  *)
(* do not answer it for the temporal part of the language.                 *)
(*                                                                         *)
(* HOW IT IS ASKED. TLA+ is linear-time and has no `EF`, so reachability   *)
(* is not directly expressible. The standard move is to check the NEGATION *)
(* as an invariant and read the counterexample as the witness:             *)
(*                                                                         *)
(*     INVARIANT NeverFires        "this permit never grants anything"     *)
(*                                                                         *)
(*   TLC reports a violation  ->  a session exists that makes it grant.    *)
(*                                The trace IS that session. NOT vacuous.  *)
(*   TLC completes clean      ->  no session of up to MaxAttempts does.    *)
(*                                VACUOUS within the bound -- the finding. *)
(*                                                                         *)
(* So a "failing" run is the good outcome and a clean one is the alarm.    *)
(* `src/checker/properties.py` inverts it before reporting, because that    *)
(* reading is a trap for anyone who glances at raw TLC output.             *)
(*                                                                         *)
(* WHAT IS DIFFERENT FROM TemporalPolicy.tla, which asks the same question *)
(* of one hand-written policy set. Two things, and both are the point:     *)
(*                                                                         *)
(*   - The policies come from `PolicyUnderTest`, GENERATED from `.dw` text *)
(*     by src/checker/properties.py. Nobody paraphrases the policy into     *)
(*     TLA+ by hand, so nothing is lost between what was written and what  *)
(*     is checked.                                                         *)
(*   - The decision is `DogwoodSemantics!Decide`, the evaluator that       *)
(*     agrees with the real Dogwood engine on 911 recorded corpus pairs    *)
(*     and on the live `error`-event scenarios. TemporalPolicy.tla instead *)
(*     carries its own `PermitFires`, which is a second reading of the     *)
(*     same language with nothing holding the two together.                *)
(*                                                                         *)
(* Together those make the deliverable "hand us a Dogwood policy and we    *)
(* will model-check it" rather than "here is a policy we modelled".        *)
(***************************************************************************)
---------------------------------- MODULE Vacuity ----------------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

CONSTANTS
    MaxAttempts,    \* bound on session length, in attempts (two events each)
    MaxAmount,      \* bound on the numeric domain input fields range over
    Target          \* index into Policies of the permit under test

ASSUME VacuityAssumption ==
    /\ MaxAttempts \in Nat /\ MaxAttempts > 0
    /\ MaxAmount \in Nat /\ MaxAmount > 0
    \* 0 selects the diff question; any rule index selects the load-bearing one.
    /\ Target \in (DOMAIN Policies) \union {0}

\* `Cases` is only read by DogwoodSemantics!Agree, which this module never calls;
\* the evaluator's Decide takes its trace and policies as arguments.
D == INSTANCE DogwoodSemantics WITH Cases <- << >>

(***************************************************************************)
(* Scalars carry their kind, because TLC refuses to compare a string with  *)
(* an integer and refuses `"alice" \in Int` as a type test. Every value    *)
(* the evaluator sees is tagged and compared kind-first.                   *)
(***************************************************************************)
\* Str / Num / Bool / Anon come from PolicyUnderTest, which a property module extends too.
\* Defining them here as well would be a multiply-defined symbol.

\* Principal and resource are held fixed. Vacuity is a question about the
\* temporal condition; varying the scope would multiply the state space to
\* explore a dimension no temporal operator reads.
\* Named for what it is, and NOT `Other` -- PolicyUnderTest uses that for the second policy set.
Stranger == Str("stranger")

(***************************************************************************)
(* WHO an event belongs to -- its principal, and the value of every field   *)
(* the schema pins.                                                        *)
(*                                                                         *)
(* One value unless a universal pin established a partition key. With one,  *)
(* every event is in every partition and a pin could exclude nothing: the   *)
(* answer would be the UNPINNED one wearing a pin's name. With two, a       *)
(* session can hold an event the decision's partition shuts out, which is   *)
(* the whole question a pin raises.                                        *)
(*                                                                         *)
(* Singleton when there is no key, so a policy checked without a schema     *)
(* explores exactly the state space it always did.                         *)
(***************************************************************************)
Whos == IF PinKeys = {} THEN {Anon} ELSE {Anon, Stranger}

Amounts == 1..MaxAmount

\* The domain a bound variable of non-Timepoint type ranges over -- what
\* `count`/`sum ... for (a: Long)` quantifies across. Every value any field can take, so a
\* binder ranges over values that actually occur rather than over an invented range.
Values == AllValues

(***************************************************************************)
(* THE REQUESTS THE AGENT MAY MAKE.                                        *)
(*                                                                         *)
(* Each field carries its OWN domain, generated from the literals the      *)
(* policy compares it against plus one it does not, so that both matching  *)
(* and not-matching are reachable. One shared domain would move every      *)
(* field together, and a policy reading two of them could then never be    *)
(* explored -- which is why such policies used to be refused outright.     *)
(*                                                                         *)
(* TLA+ has no dependent function space, so this is the full function      *)
(* space over every value, filtered to the records each field allows.      *)
(***************************************************************************)
Inputs == {g \in [InputFields -> AllValues] :
              \A f \in InputFields : g[f] \in InputDomain[f]}

Outputs == {g \in [OutputFields -> AllValues] :
               \A f \in OutputFields : g[f] \in OutputDomain[f]}

\* A request carries no outputs -- only its outcome does. The corpus traces are written that
\* way, and a predicate binding an output field must not match a request event.
NoOutput == [f \in {} |-> Str("")]

MaxTime == 2 * MaxAttempts

VARIABLES
    trace,      \* the session's recorded trajectory -- all the engine can see
    fired,      \* indices of permits that have actually GRANTED something
    widened,    \* TRUE once Policies ALLOWED something Compared denied
    narrowed    \* TRUE once Policies DENIED something Compared allowed

vars == <<trace, fired, widened, narrowed>>

\* The old single `mattered` flag, which asked only WHETHER the two sets part company. It is
\* now derived rather than stored, because the direction is the more useful question and
\* carrying both would be carrying the same bit twice.
Mattered == widened \/ narrowed

\* Once they have parted company the histories are no longer comparable: this exploration
\* drives the session with `Policies`, so after a disagreement it is walking a trajectory the
\* other set would not have produced. Everything up to the FIRST disagreement is common ground;
\* past it, nothing is. So a session contributes AT MOST ONE directional observation.
Diverged == Mattered

TypeOK ==
    /\ fired \subseteq DOMAIN Policies
    /\ widened \in BOOLEAN
    /\ narrowed \in BOOLEAN
    /\ Len(trace) \in 0..MaxTime

Init ==
    /\ trace = << >>
    /\ fired = {}
    /\ widened = FALSE
    /\ narrowed = FALSE

(***************************************************************************)
(* Events carry exactly the fields the evaluator reads: action, kind,      *)
(* input, output, principal, resource, time.                              *)
(*                                                                         *)
(* `InputFields` and `OutputFields` are generated from the policy text --  *)
(* only fields some condition actually reads are modelled, so a policy     *)
(* that joins on nothing costs nothing to check.                           *)
(***************************************************************************)
Event(action, kind, input, output, t, who) ==
    [time      |-> t,
     action    |-> action,
     kind      |-> kind,
     input     |-> input,
     output    |-> output,
     principal |-> who,
     resource  |-> Anon,
     \* A scope bind -- `callerPrincipal: principal`, `__drupe.session_id` -- reads this. It was
     \* never here, so ANY policy using one crashed TLC with "nonexistent field", a pre-existing
     \* hole this found. Tied to `who`: one caller, one session.
     session   |-> who,
     \* Every pinned field takes the event's own `who`. The keys move together, which is enough
     \* to ask whether a partition excludes an event -- and keeps the state space at one extra
     \* dimension rather than one per key.
     pins      |-> [k \in PinKeys |-> who]]

(***************************************************************************)
(* THE DECISION -- deny by default, forbid overrides permit. Cedar's       *)
(* model, which Dogwood keeps, and here it is Dogwood's own evaluator      *)
(* rather than a restatement of it.                                       *)
(***************************************************************************)
Hit(h, idx) ==
    {k \in DOMAIN Policies : D!PolicyMatches(Policies[k], h, idx, h[idx], Values)}

Allowed(h, idx) == D!Decide(h, Policies, idx, Values)

(***************************************************************************)
(* THE SECOND POLICY SET, and the verdict it would give.                   *)
(*                                                                         *)
(* Two questions share one mechanism -- compare the verdicts of two policy *)
(* sets across every session -- and differ only in what the second set is. *)
(*                                                                         *)
(*   Target > 0   `Policies` without rule Target. Is that rule             *)
(*                LOAD-BEARING? A DEAD forbid never denies anything the    *)
(*                rest would have allowed; a REDUNDANT permit fires, but   *)
(*                another permit always would too. Both are "deleting it   *)
(*                changes nothing".                                        *)
(*                                                                         *)
(*                Distinct from vacuity, and worth keeping apart: a        *)
(*                vacuous permit never fires at all where a redundant one  *)
(*                fires and is covered. Vacuous implies redundant; the     *)
(*                converse does not.                                       *)
(*                                                                         *)
(*   Target = 0   `Other`, translated from a second file. Did this EDIT    *)
(*                change any decision? The question a policy author        *)
(*                actually has when touching a set somebody else wrote.    *)
(***************************************************************************)
Without == [j \in 1..(Len(Policies) - 1) |->
               IF j < Target THEN Policies[j] ELSE Policies[j + 1]]

Compared == IF Target = 0 THEN Other ELSE Without

AllowedCompared(h, idx) == D!Decide(h, Compared, idx, Values)

\* A permit GRANTED only when it matched and the request was allowed. A permit
\* that matches but is always overridden by a forbid authorizes nothing, and
\* counting it as fired would report an inert policy as live -- the exact
\* mistake this spec exists to catch.
Granted(h, idx) ==
    IF Allowed(h, idx)
    THEN {k \in Hit(h, idx) : Policies[k].effect = "permit"}
    ELSE {}

(***************************************************************************)
(* TRANSITIONS                                                             *)
(*                                                                         *)
(* One attempt appends two events: the decision event, then its outcome.   *)
(* The outcome kind is AgentCore's convention and is what the whole        *)
(* `::response` / `::request` finding turns on -- permitted-and-completed  *)
(* is recorded as `response`, DENIED is recorded as `error`, and the       *)
(* request event is recorded either way.                                   *)
(*                                                                         *)
(* Note the attempt is NOT conditioned on being allowed. A denied attempt  *)
(* still writes a `request` event, and a permit gated on `::request` can   *)
(* fire off nothing but refusals. Requiring the decision here would hide   *)
(* precisely the case worth finding.                                       *)
(***************************************************************************)
Attempt(action, input, output, who) ==
    /\ Len(trace) + 2 <= MaxTime
    \* The request and its outcome share a `who`: one caller makes the attempt and one outcome
    \* comes back to them. Letting those differ would invent a history the gateway cannot record.
    /\ LET t       == Len(trace) + 1
           withReq == Append(trace, Event(action, DecisionKind, input, NoOutput, t, who))
           idx     == Len(withReq)
           ok      == Allowed(withReq, idx)
           \* A denied action produces no outputs either -- AgentCore records the failure,
           \* not a result.
           outcome == IF ok THEN Event(action, "response", input, output, t + 1, who)
                            ELSE Event(action, "error", input, NoOutput, t + 1, who)
       IN /\ trace' = Append(withReq, outcome)
          /\ fired' = fired \union Granted(withReq, idx)
          \* Compared on the history `Policies` produced. Sound for both questions: the two
          \* sets agree up to the FIRST point they disagree, so up to that point they have
          \* produced the same history -- and this exploration reaches it. If they never
          \* disagree along any such history, the other set produced those same histories too.
          \* Guarded by ~Diverged, which is what makes the DIRECTION sound rather than merely
          \* the fact of a difference. Without the guard a session could widen at one step and
          \* then, on a history only `Policies` can produce, appear to narrow at a later one --
          \* and the pair would be reported as incomparable on the strength of a trajectory the
          \* other set never reaches. At most one direction can hold at any single step, since
          \* `ok` is one boolean, so the first disagreement sets exactly one of these.
          /\ widened'  = (widened  \/ (~Diverged /\ ok /\ ~AllowedCompared(withReq, idx)))
          /\ narrowed' = (narrowed \/ (~Diverged /\ ~ok /\ AllowedCompared(withReq, idx)))

\* The agent may attempt anything, with any input, and an approver may return
\* either verdict. All of it is behaviour, so a VACUOUS result holds whatever
\* the agent and the approver do -- which is what makes it worth stating.
Next ==
    \E action \in Actions, input \in Inputs, output \in Outputs, who \in Whos :
        Attempt(action, input, output, who)

\* No fairness. Vacuity is a reachability question -- does ANY session make this
\* permit grant -- so nothing needs to be forced to happen.
Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* THE PROPERTY. Checked as an invariant and MEANT TO FAIL; see the header.*)
(***************************************************************************)
NeverFires == Target \notin fired

\* Also checked as an invariant and also MEANT TO FAIL. A violation is the witness
\* session where the two sets decide differently. Read it for whichever question was
\* asked: the rule is load-bearing (Target > 0), or the edit changed behaviour
\* (Target = 0). A clean run means no session of this length tells them apart.
NeverMatters == ~Mattered

\* The DIRECTIONAL pair, each also meant to fail, each checked in its own run because TLC stops
\* at the first violated invariant and we want a witness for each direction separately.
\*
\*   NeverWidened violated   `Policies` permits a session `Compared` denies -- the edit ADDED a
\*                           permission. This is the dangerous direction: a permission removed
\*                           is a support ticket, a permission silently added is an incident.
\*   NeverNarrowed violated  `Policies` denies a session `Compared` permits -- the edit REMOVED
\*                           a permission.
\*
\* Neither violated is EQUIVALENT within the bound; both violated is INCOMPARABLE.
NeverWidened  == ~widened
NeverNarrowed == ~narrowed

=============================================================================
