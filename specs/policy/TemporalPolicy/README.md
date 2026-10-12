# TemporalPolicy

## About
This directory holds TLA+ specs that model Dogwood temporal policies.

**In use: what `anchor check`, the MCP server and the drafting agent run on.**

| file | what it is |
|---|---|
| `DogwoodSemantics.tla` | the evaluator: our reading of Dogwood's temporal operators, differential-tested against the corpus. `Decide` gives the verdict for one decision in a trace |
| `Vacuity.tla` | the session model `anchor check` runs: every session up to `--attempts`, over the generated `PolicyUnderTest.tla`, each decision by `DogwoodSemantics!Decide` |

**Current, and standalone: the session-rotation finding.** Uses `DogwoodSemantics`, so it reads
policies the same way the checker does, but no Anchor command runs it; the spec tests do.

| file | what it is |
|---|---|
| `SessionRotation.tla` | what a caller who controls the session id can do |
| `SessionRotation.cfg` | aggregate cap, rotation allowed. **Cap violated** |
| `NoRotation_CapHolds.cfg` | the control: same policy, rotation disabled. Cap holds |
| `Rotation_ApprovalGateHolds.cfg` | approval gate, rotation allowed. Gate holds |
| `rotation_aggregate.dw`, `rotation_approval.dw` | the two policies, as real Dogwood text |
| `RotationPolicies.tla` | **generated** from those by `src/translator/dw_to_tla.py`. A test fails if it drifts from them |

**The original prototype: no longer used by any Anchor command.** A hand-written policy set with its
own evaluator (`PermitFires`), superseded by `Vacuity.tla` and `DogwoodSemantics.tla`, which take
the policies from the `.dw` text and share one evaluator validated against the engine. Kept because
the spec tests run it: it is the hand-built version of the `::request` finding.

| file | what it is |
|---|---|
| `TemporalPolicy.tla` | its session model and decision engine |
| `Policies.tla` | the hand-written policy set it runs on. Nothing else uses it |
| `TemporalPolicy.cfg` | approvals permitted; the sell permit gated on `::response`. **Satisfiable** |
| `Vacuous_ForbiddenApproval.cfg` | approvals forbidden, same permit. **Vacuous** |
| `RequestGated_SurvivesForbid.cfg` | approvals forbidden, permit gated on `::request`. **Satisfiable — and that is the bad news** |

Run a spec from this folder, since TLC looks for the module in the current directory and fails with
"Cannot find source file" when given a path from elsewhere:

```bash
cd specs/policy/TemporalPolicy
java -cp ../../../lib/tla2tools-1.7.4.jar tlc2.TLC -cleanup -config SessionRotation.cfg SessionRotation.tla
```

## How these specs verify a policy set

Nothing here models one policy. These specs model the **engine**, and a policy set is data fed to
it. Four pieces, and which are generated matters:

| piece | who writes it | what it holds |
|---|---|---|
| `DogwoodSemantics.tla` | by hand, once | what the engine does with *any* policy set |
| `PolicyUnderTest.tla` | **generated** from a `.dw` by `anchor check`, per run | that file's rules, as a TLA+ sequence, and the vocabulary its conditions read. Regenerated every run; the copies under `traces/` folders are kept evidence (`--keep`, `--full`), never an input |
| `Vacuity.tla` | by hand, once | the session model and the derivable questions (`NeverFires`, `NeverMatters`), asked of `PolicyUnderTest` |
| a property module + `.cfg` | by hand or drafted, per requirement | an intentional claim, and the sessions to check it over. Extends `PolicyUnderTest` in place of `Vacuity.tla` |


**The set is combined mechanically, in one operator.** `DogwoodSemantics!Decide` quantifies over
every rule in it:

```tla
Decide(trace, policies, idx, values) ==
    LET dec  == trace[idx]
        seen == values \union TraceScalars(trace)
        hit  == {k \in DOMAIN policies : PolicyMatches(policies[k], trace, idx, dec, seen)}
    IN /\  \E k \in hit : policies[k].effect = "permit"
       /\ ~\E k \in hit : policies[k].effect = "forbid"
```

Allowed iff **some** matching rule permits and **no** matching rule forbids, with default-deny
falling out of the empty `hit` case. That `DOMAIN policies` is where cross-rule reasoning lives, and
it is why "is this forbid dead?" has an answer here and none in a per-rule validator: a forbid is
inert *given the rest of the set*, which is not a fact about the forbid.

The permit/forbid combination is the easy half, and it is Cedar's. The temporal half sits in
`PolicyMatches`, which takes the whole trace and a time point:

```tla
PolicyMatches(p, trace, upto, dec, values) ==
    /\ p.actions = {} \/ dec.action \in p.actions
    /\ CondHolds(p.cond, trace, upto, dec, << >>, values)
```

`CondHolds` is where event kinds (`::request` / `::response` / `::error`), `within` windows and
aggregates over history are decided -- the part Cedar does not have.

**A property module states a claim about that function's output**, over a session set it chooses:

```tla
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest   \* generated: carries `Policies`
D == INSTANCE DogwoodSemantics WITH Cases <- << >>         \* the engine, above
Allowed(s) == D!Decide(Session(s), Policies, Len(Session(s)), AllValues)
```

Two things follow that are easy to state wrongly:

- **The claim is authored from the requirement, never derived from the rules.** Rules carry no
  asserts, so there is nothing per-rule to combine. A claim read off the policy set is a
  restatement of it and will hold no matter what the set does.
- **The quantification is over sessions, not over time.** These modules set `Next == UNCHANGED`, so
  the reachable states *are* the initial states: TLC enumerates a chosen finite set of sessions and
  evaluates the invariant on each. That is why a verdict reads "violated by the initial state". It
  is bounded model checking, and the bound is the session set rather than a trace depth.

The sharpest claims are often not "x must be permitted" but **"these two sessions must decide the
same"**. A requirement that says *transferred* is violated by a policy set that counts *attempts*,
and the way to say so is that a refused attempt must leave the verdict unchanged.

## Read the result backwards

`Vacuity.tla`'s questions are written to **fail**. `NeverFires` claims a permit never grants;
`NeverMatters` claims deleting a rule never changes a decision (see
[the checker](../../../src/checker/README.md#how-a-check-runs) for how the two combine into a verdict):

| TLC says | means |
|---|---|
| **Invariant violated** | a witness exists: the permit can grant, or the rule matters. The counterexample is the *witness session* proving it |
| **No error found** | the permit is **vacuous**, or the rule is redundant or dead. This is the bad outcome, and it is the quiet one |

TLA+ is linear-time and has no `EF`, so reachability is posed as the negation of an invariant and
the trace is read as the witness. Everywhere else in this repo that is a workaround; here it is the
whole tool.

**The prototype's configs are only meaningful together.** A check that can only ever report "no
violation" proves nothing — a broken engine in which nothing ever fires would pass the vacuity check
trivially. In `TemporalPolicy.tla`, which asks `NeverFires` alone, the two satisfiable configs are
the control: they demonstrate the machinery *can* find a witness, which is what makes the absence of
one in `Vacuous_ForbiddenApproval` informative.

## Why this exists

AgentCore's temporal policies — written in **Dogwood**, a Cedar superset — decide using the history
of a session rather than the current request alone. From the announcement's own limitations:

> temporal conditions do not currently support the powerful automated reasoning analysis tools that
> Cedar provides

Cedar has symbolic analysis: equivalence, subsumption, satisfiability. Temporal policies have none
of it. So Dogwood **enforces** a policy on the session that happens, and nothing checks that the
policy set means what its author intended across the sessions that could happen. That second thing
is model checking.

## What is modelled

Enough MFOTL to pose the question honestly:

| | |
|---|---|
| **metric** | `Window` — a bounded look-back, standing for `within 1h` |
| **first-order** | a join between an earlier event and the request being decided, `input.stock: context.input.stock`. Not "some approval happened" but "an approval for **this** stock". A propositional temporal logic cannot express that join, and it is the whole reason the logic is first-order |
| **past-time** | history only. An authorizer decides *now*, from what has already happened — you cannot gate a permit on a future obligation without blocking |

The agent is not modelled: it attempts any request at any time, and `ApproveSale` may return either
verdict. Both are behaviours, so a result holds whatever the agent and the approver do — the same
stance every other spec here takes.

## What this does not establish

- **It is not a model of Dogwood, and it models two layers at once.** Dogwood the *language* has no
  fixed event vocabulary — its grammar says "event kinds are author-defined, not a fixed set —
  `request` / `response` are merely the conventional ones", and a schema marks one of them the
  `decision event`. `error` is not a Dogwood concept at all: it is **AgentCore's** convention for
  recording a denied action. The event schema (`--event-schema`, or Dogwood's default without one)
  supplies the language's vocabulary, kept separate from that convention, but every finding here is
  about the service convention, not the language.
- **The `error` rule is confirmed by the engine, not by the corpus.** Across all 521 cases in
  `tests/passing/temporal_only/corpus`, `::error` appears in **zero** policies and **zero** traces,
  so for a long time the finding rested on the devguide alone. It no longer does: the built engine
  judges traces we construct, and it agrees — see [below](#the-engine-judges-traces-the-corpus-never-recorded).
  What that costs is that the check needs a compiled binary, so it skips where the corpus half runs
  anywhere.
- **The differential test covers `DogwoodSemantics.tla`, not the session model.** The evaluator
  agrees with the reference implementation on **911 recorded pairs** — see below. What is still
  unchecked is most of what `Vacuity.tla` adds on top: the session model and `Granted`. The
  request/response/error recording convention is the exception — the replay harness puts that one
  in front of the engine directly.
- **Bounded sessions.** `MaxAttempts`, which is `--attempts` (default 3), each attempt being two
  events. "Vacuous" here means *no session of up to that many attempts fires it*. A permit needing a
  longer setup would be reported vacuous when it is merely deep. Raise the bound to trade runtime for
  confidence; this is the ordinary bounded-model-checking caveat and it does not go away.
- **Not all of Dogwood.** The prototype, `TemporalPolicy.tla`, modelled `formerly within` alone.
  `DogwoodSemantics.tla` adds `previous`, `since` and the `count`/`sum` aggregations (see the
  construct table below); what the checker still refuses is listed under
  [What is modelled, and what is refused](#what-is-modelled-and-what-is-refused).

## The finding this reproduces

The policy is the trading example from the AgentCore docs:

```
permit (principal, action == "SellShares", resource == gateway)
when temporal {
    formerly within 1h Action::"ApproveSale"::response{
        input.stock:     context.input.stock,
        output.approved: true
    }
};
```

Now add one unrelated rule — approvals are tightened, by someone who never read the sell rule:

```
forbid (principal, action == "ApproveSale", resource);
```

The SellShares permit is **untouched**. It still parses, still validates, still references a real
action. And it can never fire again, because:

> a permitted action that completes is recorded as a `response` event, and an action that a policy
> denies is recorded as an `error` event. A temporal condition matches only events of the kind it
> names

`::response` never matches, so the condition is unsatisfiable, so the permit is dead. **Nothing
about either policy read on its own says so** — it is a property of the set, and that is exactly
what per-policy review misses and a model checker does not.

The prototype's three configs, run against the hand-written `TemporalPolicy.tla`:

```
TemporalPolicy                   SATISFIABLE
Vacuous_ForbiddenApproval        VACUOUS
RequestGated_SurvivesForbid      SATISFIABLE
```

`anchor check` now reaches the same verdicts from the `.dw` text itself: see
[It reproduces the hand-written spec's finding](#it-reproduces-the-hand-written-specs-finding).

## One word apart, opposite security properties

That third row is the sharper finding, and it came out of reading the reference corpus.

AgentCore records a `request` event for **every** attempt, permitted or not; only the outcome
differs — `response` when allowed, `error` when denied. So these two gates are not variations on a
theme:

| gate | matches | survives `forbid ApproveSale`? |
|---|---|---|
| `ApproveSale::response{...}` | an approval that was permitted **and completed** | no — goes vacuous |
| `ApproveSale::request{...}` | somebody **tried** to get an approval | **yes** — fires on denied attempts |

The second reads like an approval gate and is not one. It grants precisely the capability the
approval existed to protect, off a sequence of refusals. Same engine, same policy set, same forbid —
the event kind is doing all the work.

The corpus made this visible: `::request` appears in 555 policy files against `::response`'s 94, so
the *conventional* form is the weaker one. It does not, however, contain a single `::error`, so for
a while this table was read off the devguide rather than executed. It is executed now — the built
engine returns DENY for the first row and ALLOW for the second, on the same denied approval. See
[The engine judges traces the corpus never recorded](#the-engine-judges-traces-the-corpus-never-recorded).


## Checked against the reference implementation

The largest caveat on this spec used to be that it modelled the *documented* rules with nothing
confirming the reading. Dogwood's own repository closes it: its temporal regression corpus is 521
cases, each pairing a policy set and an event trace with **the verdicts their engine produced**.

```bash
python tests/strands/dogwood_differential.py
```

```
checked   923 (trace, expected) pairs from 478 cases, in one TLC run
  AGREE
```

The subset covers `formerly within`, `previous within`, `since within`, `&&`, `!`, `when`/`unless
temporal`, and the `count`/`sum` aggregations with `tp()` timepoint binders. It also covers the
**Cedar level** a temporal block sits inside — `when { ... }` with no temporal part at all,
several clauses in sequence, `||`, and a `temporal { ... }` block used as one operand among
others — because that is the shape most real policies have, and a checker that handles only
`when temporal { ... }` handles almost none of them. Every construct is
genuinely exercised, so the agreement means something for each rather than resting on the common
one:

| construct | accepted cases using it |
|---|---|
| `formerly` | 254 |
| `since` | 68 |
| `tp()` | 55 |
| `sum` | 36 |
| `previous` | 34 |
| `count` | 24 |

**None of these has documented semantics we could find.** They are written as standard past-time
MFOTL and the corpus is the only reason to believe that reading — so each is mutation-checked
independently, and all six turn the run red:

```
window (metric bound)    caught      tp binding               caught
previous index           caught      count vs sum             caught
since continuity         caught      self-inclusion (upto)    caught
```

**The detail is in [VALIDATION.md](VALIDATION.md):** the second corpus of whole policies, how
`count` was decoded, how the modelled constructs were chosen, and what the first run caught.

## A policy's meaning is not in its own text

The sharpest thing the corpus taught us, and the thing that caught our translator on its first run.

An `event.dwschema` can **pin** a field, forcing every event's copy of it to equal something about
the decision:

```
decision event <A>::request {
    ...inputs(A),
    pin callerPrincipal: principalType(A) = principal,
}
```

The policy never writes `callerPrincipal`, cannot see it, and cannot bypass it. In
`1117_pin_principal_correlation` the written condition correlates on `input.user` and matches —
and the engine denies anyway, because the pin requires the prior Login's principal to equal the
reader's. Read the `.dw` and ignore the schema and you get a different answer than the engine.

### Universal versus partial, which is the half that bites

A pin declared on **every** event kind is *universal* and switches the leaf to key-local
semantics: the trace is partitioned by the pinned key and temporal operators see only the
decision's own partition. A pin declared on **some** kinds is *partial*, earns no isolation, and
stays global. The corpus puts it plainly — "the engine must not grant isolation the schema did not
earn."

The distinction is invisible to `formerly`, `count` and `sum`. They are existential, so restricting
the candidates is the same as adding a conjunct, and an implementation that only injected conjuncts
would pass every one of those cases.

It is visible to **`previous`**, which means *the most recent match*:

| | global (partial pin) | partitioned (universal pin) |
|---|---|---|
| a foreign event is the most recent | it **is** the `previous`, and fails the predicate → deny | skipped entirely → the most recent of *mine* is used → permit |

`1155_relativize_previous_ignores_foreign` and `1164_partial_pin_stays_global` are **the same
policy and the same trace**, differing only in whether the pin covers both event kinds — and they
have opposite verdicts. That pair is why pins are modelled as partitioning rather than as injected
conjuncts, and both directions are mutation-checked: treating every pin as universal turns the run
red, and so does dropping partitioning and keeping the conjuncts.

### What is modelled, and what is refused

Universal and partial pins on the two **scope** fields, `callerPrincipal` and `callerResource`,
plus universal pins on the nested reserved leaf `__drupe.session_id`. That last one partitions by
**session** — it confines a policy to its own session without the policy ever mentioning sessions —
and `1158_relativize_two_pins_both_required` pins it *alongside* `callerPrincipal`, so two keys must
hold at once.

`1122_pin_disagree_denies_despite_author_literal` is the other half of the contract, and it needed no
rule of its own. The policy writes `__drupe.session_id: "sess-1"` itself; partitioning already
confines candidates to the decision's own session, so an author literal naming a different one leaves
nothing that can satisfy both — the permit is unsatisfiable rather than merely unmatched.

A pin on a **context field** partitions the same way — `1161_relativize_context_key` makes one
the *sole* key, with principal and resource left unpinned, so nothing else confines evaluation.
Rather than a field per pin kind, every event carries a `pins` record holding the value of each
field the schema pins; `principal` and `resource` stay special only because they come from the
event's `scope(...)` envelope rather than its payload.

Context pins must be **symmetric** — the context path they read has to be the field path they
constrain, which is the schema's own definition. An asymmetric pin relates two different things
and is refused rather than treated as this one.

Refused, each being a separate feature rather than a spelling of this one:

- deeper paths under `__drupe` than the single `session_id` leaf
- asymmetric pins, where the context path read differs from the field constrained
- schemas with custom event kinds (`attempt`/`outcome` instead of `request`/`response`)
- the **nine** schema-bearing cases with no pin at all, which are in the corpus for renamed
  reserved fields, deep paths and injected slots

That last group is worth naming: the old refusal message said "event schema pins a field into every
predicate" for all 30 schema cases, and a third of them contain no pin. The message now says which
feature actually stopped it.

**Two assumptions, stated because they are load-bearing.** Each was checked across the whole
corpus rather than assumed, and either would make the model *wrong* rather than merely
incomplete if a trace broke it:

| assumption | checked |
|---|---|
| an event's `callerPrincipal` is its `scope(...)` principal | 4371 events, never diverge |
| a decision's `context.__drupe.session_id` is its own payload's | 20 decision events, never diverge |

The model reads the second of each pair.


## The checker takes arbitrary policy text

For a long time this directory model-checked *one* policy, hand-written into `Policies.tla` as a
`PermitFires` CASE expression. That is a paraphrase, and nothing checks a paraphrase. `Vacuity.tla`
removes both hand-written halves:

```
any .dw ──> translator  ──> PolicyUnderTest.tla ──┐
                                                    ├──> TLC, once per permit
                          Vacuity.tla ──────────────┘
```

- The **policies** come from the parser that agrees with the reference implementation on 914
  recorded corpus pairs, so what is checked is the policy as written.
- The **decision** is `DogwoodSemantics!Decide` — the same evaluator, validated against those pairs
  and against the live engine on the `error` scenarios.
- The **vocabulary** is lifted from the policy too: only the actions, event kinds and input/output
  fields some condition actually reads get modelled, so a policy that joins on nothing costs
  nothing to check.

What is left hand-written is the *session model* — that an attempt records a decision event and
then an outcome, and that the outcome kind is `response` when allowed and `error` when denied.
That is AgentCore's convention rather than the policy's content, and it is the thing the replay
harness checks against the real engine.

### It reproduces the hand-written spec's finding

The strongest evidence that the generalisation is faithful. `docs_trading.dw` is the AgentCore
documentation's trading example — the same policy `TemporalPolicy.tla` models by hand:

```
docs_trading.dw            permit #1  action == ApproveSale   live      witness: ApproveSale
                           permit #2  action == SellShares    live      witness: ApproveSale -> SellShares

docs_trading_forbidden.dw  permit #2  action == SellShares    VACUOUS
```

Same result as `Vacuous_ForbiddenApproval.cfg` reaches through the hand-written model. The two
share no code on the path that matters — different policy representation, different decision
function — so this is a cross-check rather than a restatement. Both specs stay in the tree for
exactly that reason.

It also exercises the two constructs the smaller cases do not: the first-order join
(`input.stock: context.input.stock` — *an approval for **this** stock*, which a propositional
temporal logic cannot express) and an output-field bind (`output.approved: true`).

### The two shapes of vacuity

| shape | example | why a satisfiability check misses it |
|---|---|---|
| the condition can never hold | `approval_gate_response.dw` | the condition is satisfiable *in principle* — it just needs an event this policy set can never produce |
| it holds, and a `forbid` wins | `overridden_permit.dw` | the condition is `true`. The permit matches every request and grants none |

The second is why the spec tracks **granted** rather than **matched**. `Granted` returns the
matching permits only when the request was actually allowed; counting a matched-but-overridden
permit as live would report an inert policy as working.

### Reading a VACUOUS verdict honestly

**VACUOUS is bounded, and it is the direction that must never be wrong.** It means *no session of
up to `--attempts` attempts makes this permit grant*, not *never*. A permit needing a longer setup
is reported vacuous when it is merely deep — and that is the dangerous error, because it would send
someone to delete a control that works. Three things are done about it:

- The verdict is **falsification-tested**, not merely observed. Adding `permit (action ==
  ApproveSale)` to `approval_gate_response.dw` flips it to live, so the VACUOUS is attributable to
  the approval being denied rather than to the model being unable to reach a `response` at all.
- Anything that is **not an answer** — a parse error, an unsupported construct, a `TypeOK` failure
  — raises rather than being reported as vacuous. Silence must never read as a finding.
- Constructs outside the modelled subset are **refused**, with the reason, rather than
  approximated. What is left to refuse is a bound on state space rather than on soundness: the
  request space is the product of the fields' domains, so `--max-fields` caps how many a policy
  may read (default 4).

**Each field carries its own domain**, and that domain is derived from the literals the policy
actually compares the field against, plus one it does not — so both matching and not-matching stay
reachable. Two things turned on this:

| before | after |
|---|---|
| one shared domain moved every field together, so a policy reading two was **refused** — 142 of 419 parseable corpus policies, **34%** | fields move independently; **419 of 419** accepted |
| every output field was a **boolean**, so a gate on a string output could never match | the domain follows the literal, so `output.result: "ok"` matches |

That second row was a **false VACUOUS** — a working permit reported inert, which is the one wrong
answer this tool must not give, and eight output binds in Dogwood's own corpus compare against a
string. [`string_output.dw`](../../../tests/policies/string_output.dw) pins it. Mutation-checked:
ignoring the literals a policy names brings the false VACUOUS straight back.

A `live` verdict needs no such care: it comes with a witness session, which is evidence rather
than an absence.

### Beyond vacuity: is each rule load-bearing?

Vacuity asks whether a permit can ever grant. The wider question is whether a rule **decides
anything at all**, and it has one definition:

> A rule is load-bearing when **deleting it changes some verdict**. If no session notices its
> removal, it can go.

That covers both of the things worth reporting about an inert rule, with the same machinery:

| verdict | what it means | why it matters |
|---|---|---|
| **VACUOUS** | the permit never fires in any session | a **bug** — whatever it was meant to allow is unreachable |
| **REDUNDANT** | it fires, but another permit always would too | works fine, and the next reader still has to work out that it decides nothing |
| **DEAD** | the forbid never denies anything the rest would have allowed | somebody wrote it believing they were closing something already shut |

**The three are not collapsed, because they are different findings.** Vacuous *implies* redundant,
so a checker that only asked the wider question would answer "redundant" for a broken permit and
bury a bug under a tidiness note. [`redundant_permit.dw`](../../../tests/policies/redundant_permit.dw)
is the case that pins the distinction: its second permit fires perfectly well and is still
deletable, and the suite asserts it is *not* reported vacuous.

A dead forbid deserves one more sentence than tidiness allows. It is inert **given the rest of the
set** — so if the permit it was guarding against is ever added, it silently starts mattering, and
nobody will connect the two changes.

```bash
./anchor check tests/policies/dead_forbid.dw
```
```
  permit #1  action == Trade         live      witness: Trade
  forbid #2  action == Approve       DEAD      deleting it changes no verdict in any session
      the condition is not why -- it is inert even with no condition at all
```

**The comparison is exact, not an approximation.** `Vacuity.tla` evaluates both the full policy set
and the set without `Target` at each decision, on histories the **full** set produced. If they agree
at every decision along every such history, the reduced set would have produced those same
histories — by induction on the trace — so agreeing everywhere really does mean the rule is
deletable. Mutation-checked where it would silently over-report: make the "set without this rule" a
no-op and every rule reports redundant, which the `live` assertion catches.


### Policy diff: did this edit change anything?

The third question the same machinery answers, and the one a policy author actually has. Not *is
this rule inert* but **I am editing a set somebody else wrote — what did I just change?**

```bash
./anchor check tests/policies/docs_trading.dw \
    --against tests/policies/docs_trading_forbidden.dw
```
```
docs_trading.dw vs docs_trading_forbidden.dw: 2 rule(s) vs 2, bound 3 attempts

  MORE PERMISSIVE   this edit ADDS permissions

  ADDED     a session this policy permits and the old one denies:

              1. ApproveSale(stock = 1)  allowed  (approved = false)   <- docs_trading_forbidden.dw DENIES this
```

One TLC run rather than one per rule: `Target = 0` selects the second file as the set compared
against, and a `NeverMatters` violation is the witness session.

**There is no separate spec for it, deliberately.** Redundancy already compared two policy sets —
the full one and the full one minus a rule — so a diff is the same question with the second set
coming from a different file. A `PolicyDiff.tla` would have duplicated the session model, and two
copies of a model drift: a fix to the outcome-kind convention in one would leave the other quietly
checking something else. This directory carries `src/translator/dw_to_tla.py --check` for exactly that reason.

### "No difference" is the answer that must never be wrong

It tells someone their edit was safe, so it gets the same care as VACUOUS. Two things hold it up.

**The vocabulary spans both files.** A version that permits an action the other never mentions
would otherwise never have that action attempted, and the run would report no difference having
never looked. [`added_action.dw`](../../../tests/policies/added_action.dw) pins it, and dropping the
union turns that case red — it reports "no difference" for two files that plainly differ.

**Driving the exploration with one set is sound.** Verdicts are compared on histories `Policies`
produced, which looks asymmetric. It is not: the two sets agree up to the *first* decision where
they disagree, so up to that point they have produced the same history, and this exploration
reaches it. If they never disagree along any such history, the other set produced those same
histories too.

### The findings check each other

`redundant_permit.dw` has a gated permit the checker reports REDUNDANT.
[`redundant_permit_minimal.dw`](../../../tests/policies/redundant_permit_minimal.dw) is what you get
by acting on that advice, and diffing the two reports **no difference** — so the advice was safe.
"Deleting this rule changes no verdict" and "these two files decide identically" are the same claim
approached from opposite ends; a disagreement between them would mean one is wrong. The same holds
for `dead_forbid.dw` minus its DEAD forbid.


### Mutation-checked

| mutation | what breaks |
|---|---|
| `Granted` drops its `Allowed` guard | `overridden_permit.dw` reports live |
| denied attempts recorded as `response` | `approval_gate_response.dw` reports live |
| the without-a-rule set drops nothing | **every** rule reports redundant -- the failure a broken removal makes |
| the vocabulary is not unioned across both files | the diff reports *no difference* for files that plainly differ |

Each is chosen to be the mistake a reasonable implementation would actually make, not an
arbitrary break. All four are in the test suite's assertions, so each turns the build red
rather than merely changing a printout.


## The engine judges traces the corpus never recorded

The corpus is a large oracle but a fixed one: it answers only about traces Amazon happened to
record, and the blind spot is the one place this spec most needs an answer. Building `dogwood-cli`
turns the oracle live — it will judge any trace we hand it, including event kinds the corpus never
uses.

```
approval_gate_*.dw ─┬─ dogwood replay ─────────────────────────> verdicts (the oracle)
                    └─ translator  ──> TLA+ ──> TLC ─────────> our verdicts
```

Both sides read the same policy file, so a disagreement is ours. The three gates are checked in and
differ by exactly one word:

| policy | gate | what it is for |
|---|---|---|
| [`approval_gate_response.dw`](../../../tests/policies/approval_gate_response.dw) | `Approve::response` | the strong form — requires an approval that completed |
| [`approval_gate_request.dw`](../../../tests/policies/approval_gate_request.dw) | `Approve::request` | the weak form, and the conventional one |
| [`approval_gate_error.dw`](../../../tests/policies/approval_gate_error.dw) | `Approve::error` | rules out the duller explanation, below |

[`dogwood_replay.py`](../../../tests/strands/dogwood_replay.py) runs five scenarios over them. The
traces are generated in the harness — they are the history to evaluate against, where the policies
are what is under test. The engine's verdicts, which are what the run prints:

| policy | history | verdict at the trade | what it settles |
|---|---|---|---|
| `..._response.dw` | approval **denied** | **DENY** | an `error` is not a `response`, so the gate stays shut |
| `..._request.dw` | approval **denied** | **ALLOW** | the attempt was recorded, so the weaker gate opens — the finding |
| `..._response.dw` | approval allowed | ALLOW | the control: with a real response the same gate opens |
| `..._response.dw` | nothing at all | DENY | deny by default |
| `..._error.dw` | approval **denied** | ALLOW | a policy *can* match error events, if it says so |

The second row is the whole point. Two policies one word apart, opposite security properties, and
the difference is invisible to a syntax checker because both parse and both are satisfiable. Rows
one and two together are the claim: it is not that a denied approval is unrecorded, it is that it is
recorded *under a different kind*.

The fifth row earns its place. Without it, "the response gate stays shut" is also consistent with
`error` events being invisible to temporal matching altogether, which would be a fact about the
engine rather than about AgentCore's recording convention. It is the convention.

Our semantics agrees with the engine on all five. Mutation-checked three ways: making `Matches`
ignore the event kind, making `error` count as a `response`, and editing `approval_gate_response.dw`
to say `::request` — that last one flips the first row to ALLOW and fails the C# assertion, which is
what shows the checked-in policy is the thing being judged rather than a copy of it.

It needs the built binary, which is not in the repo, so
`PythonHarnessAttribute.RequiresExecutable` skips the C# test rather than failing it when the tree has not
been built. Build it with no feature flags. The `net` feature would make evaluation
non-deterministic and network-dependent, which is exactly what this spec assumes away; it cannot
arrive by accident, only via `--features net` or `--all-features`.

```
cargo build --release --locked --manifest-path ext/dogwood/Cargo.toml
```


## Session rotation, and which policy shapes survive it

AgentCore scopes temporal history to a **policy session**, and the session id travels in a
caller-supplied header. AWS says what follows, in their own security considerations:

> Because temporal history is scoped to a session and the session ID is supplied by the caller, a
> `count`-based limit such as "at most N calls per session" counts only the events recorded for that
> session. Starting a new session begins a new count, so a temporal rate limit constrains activity
> within a session rather than across all of a caller's sessions.

So the behaviour is documented and this is **not a discovery**. What it adds is a trace, and a
finding about policy *shapes* that is not written down anywhere.

```
SessionRotation                VIOLATED: Invariant GlobalCapHolds is violated.
NoRotation_CapHolds            HOLDS
Rotation_ApprovalGateHolds     HOLDS
```

The attack is three steps, against a cap of 3:

```
State 2: hist = <<[action |-> "Trade", amount |-> 2]>>   traded = 2
State 3: hist = <<>>                                     traded = 2     \* rotate
State 4: hist = <<[action |-> "Trade", amount |-> 2]>>   traded = 4
```

**The control is the load-bearing half.** `NoRotation_CapHolds` runs the same policy and the same
adversary with rotation disabled, and the cap holds. Without it the violation could be any modelling
error; with it, rotation is the only thing that differs.

It doubles as proof that the aggregate is live: if the `forbid` never fired, the cap would be
breached without any rotation at all. Mutation-checked both ways — making the forbid unreachable, or
summing over the timepoint binder instead of the amount, each breaks the control.

### The asymmetry

On a fresh trajectory the history is empty, and the two policy shapes go in opposite directions from
that single cause:

| shape | on an empty trajectory | |
|---|---|---|
| **permit** gated on a prior event | does not fire → default deny | **fails closed** — rotation costs the caller the capability |
| **forbid** on an aggregate (`count`, `sum`) | sees zero → does not fire → allowed | **fails open** — rotation hands the caller a fresh allowance |

Budget caps, rate limits and mutual-exclusion rules are all the second shape. Approval gates are the
first. Of the seven policies in the AgentCore banking example, roughly four are aggregates.

**Self-referential inclusion is modelled**, because AgentCore documents that "when a temporal
condition references the same action that is being authorized, the current request's own event is
included in the evaluation". The aggregate therefore counts the trade being decided, which is what
makes the cap bite at the right point rather than one trade late.

### What this does not establish

- **The policy is real Dogwood, but the *trace* is ours.** Events are synthesised by this spec in
  the shape `DogwoodSemantics` expects; nothing checks that AgentCore records a session the same
  way. The corpus validates the evaluator against recorded traces, not our construction of new
  ones.
- **Bounded.** Six steps, a cap of 3, trades of 1–2. Enough to exhibit the attack, not a claim about
  larger configurations.
- **Rotation is modelled as free.** In reality a caller must be able to set the header, and a
  deployment that derives the session id server-side would not have this exposure at all. Whether
  that is possible is a deployment question this spec cannot see.

  
