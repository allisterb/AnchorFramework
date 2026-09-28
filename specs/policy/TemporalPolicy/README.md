# TemporalPolicy

**Three questions about a session-aware authorization policy set**, each answered by exploring every
session a bounded run can have and reporting either a **witness** or a bounded no:

| question | answer |
|---|---|
| Can this permit ever grant anything? | a witness session, or **VACUOUS** |
| Is this rule load-bearing, or can it be deleted? | a witness, or **REDUNDANT** / **DEAD** |
| Did this edit change any decision? | a witness, or **no difference** |

The first is the one AWS says their tooling does not answer: a permit that can never fire is a
silent deny-everything. It reads correctly, it validates, it deploys, and the capability it exists
to allow is simply gone. The other two came out of the same machinery, because all three are
really "compare what these policies decide, across every session".

**Vocabulary, because Dogwood inherits Cedar's and it reliably trips people up.** A
**policy** is one `permit` or `forbid` statement; a `.dw` file is a **policy set**. This README
says *rule* wherever *policy* would be ambiguous, and *policy set* for the file. The distinction is
the point of all three questions above: each is about what the **set** decides, and none of them
can be answered by reading a statement on its own.

*Policy set* is Dogwood's own term, not ours: its CLI guide says every command "takes the policy
set as a positional argument (a `.dw` file"
([`dogwood-docs/guide/12-cli.md`](https://github.com/dogwood-policy/dogwood/blob/c6237c88099b3f492ecc5fcee42df06a19224b97/dogwood-docs/guide/12-cli.md),
at the commit `ext/dogwood` pins), and its parser produces a `ParsedPolicySet` and a
`LoweredPolicySet`, after Cedar's `PolicySet`. AWS's AgentCore posts say *policy document* for the
natural-language text a policy set is authored *from* — the brief here — never for the `.dw` file.

A **session** is one AgentCore
[*policy session*](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html):
"a sequence of related Gateway invocations grouped under one session ID", whose history is all a
temporal condition can see. The specs here range over every possible session up to a bound
(`--attempts`, 3 by default), never over one recorded session. Within a session Dogwood can narrow
the history further: its default event schema pins `callerPrincipal`, which is what `--pinned`
models.

**Point it at any `.dw` file:**

```bash
./anchor check tests/policies/docs_trading_forbidden.dw
```
```
docs_trading_forbidden.dw: 1 permit(s), 1 forbid(s), bound 3 attempts

  forbid #1  action == ApproveSale   DEAD      deleting it changes no verdict in any session
  permit #2  action == SellShares    VACUOUS   no session of up to 3 attempts makes it grant
      because: formerly within 1h ApproveSale::response{ input.stock: 'stock', output.approved: True }
```

Nothing about that policy set is hand-modelled — see
[the checker](#the-checker-takes-arbitrary-policy-text) below.

| file | what it is |
|---|---|
| `Vacuity.tla` | **the generic checker**: any parsed policy, any permit, evaluated by `DogwoodSemantics` |
| `TemporalPolicy.tla` | the original, hand-written: its own session model and its own decision engine |
| `DogwoodSemantics.tla` | our reading of `formerly within`, checked against the reference corpus |
| `Policies.tla` | the policy set — swappable, like `Workflow.tla` under [`DependencyDAG`](../../strands/DependencyDAG) |
| `TemporalPolicy.cfg` | approvals permitted; the sell permit gated on `::response`. **Satisfiable** |
| `Vacuous_ForbiddenApproval.cfg` | approvals forbidden, same permit. **Vacuous** |
| `RequestGated_SurvivesForbid.cfg` | approvals forbidden, permit gated on `::request`. **Satisfiable — and that is the bad news** |
| `SessionRotation.tla` | what a caller who controls the session id can do |
| `SessionRotation.cfg` | aggregate cap, rotation allowed. **Cap violated** |
| `NoRotation_CapHolds.cfg` | the control: same policy, rotation disabled. Cap holds |
| `Rotation_ApprovalGateHolds.cfg` | approval gate, rotation allowed. Gate holds |

And the policy inputs — real Dogwood text, checked in, which is what the tooling reads:

| `.dw` file | what it demonstrates |
|---|---|
| [`docs_trading.dw`](../../../tests/policies/docs_trading.dw) | the AgentCore docs' own trading example. Both permits live |
| [`docs_trading_forbidden.dw`](../../../tests/policies/docs_trading_forbidden.dw) | one line different. **The sell permit is vacuous** |
| [`approval_gate_response.dw`](../../../tests/policies/approval_gate_response.dw) | gated on a completed approval. **Vacuous** on its own |
| [`approval_gate_request.dw`](../../../tests/policies/approval_gate_request.dw) | one word different. Live |
| [`approval_gate_error.dw`](../../../tests/policies/approval_gate_error.dw) | matches the denial itself. Live |
| [`overridden_permit.dw`](../../../tests/policies/overridden_permit.dw) | matches everything, grants nothing. **Vacuous**, second shape |
| [`rotation_aggregate.dw`](rotation_aggregate.dw) | the spend cap `SessionRotation` defeats |
| [`rotation_approval.dw`](rotation_approval.dw) | the approval gate it cannot |

New to TLA+? [`specs/strands/DependencyDAG/README.md`](../../strands/DependencyDAG/README.md) has a notation primer.

```bash
java -cp lib/tla2tools-1.7.4.jar tlc2.TLC -cleanup \
    -config specs/policy/TemporalPolicy/TemporalPolicy.cfg specs/policy/TemporalPolicy/TemporalPolicy.tla
```

## How these specs verify a policy set

Nothing here models one policy. These specs model the **engine**, and a policy set is data fed to
it. Three pieces, and which are generated matters:

| piece | who writes it | what it holds |
|---|---|---|
| `DogwoodSemantics.tla` | by hand, once | what the engine does with *any* policy set |
| `Policies.tla` | by hand | the policy set the hand-written spec runs on -- swappable |
| `PolicyUnderTest.tla` | **generated** from a `.dw` | that file's rules, as a TLA+ sequence |
| a property module + `.cfg` | by hand, per requirement | the claim, and the sessions to check it over |

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

This spec checks `NeverFires`, and **means it to fail**:

| TLC says | means |
|---|---|
| **Invariant violated** | the permit is **satisfiable**, and the counterexample is the *witness session* proving it |
| **No error found** | the permit is **vacuous**. This is the bad outcome, and it is the quiet one |

TLA+ is linear-time and has no `EF`, so reachability is posed as the negation of an invariant and
the trace is read as the witness. Everywhere else in this repo that is a workaround; here it is the
whole tool.

**The configs are only meaningful together.** A check that can only ever report "no violation"
proves nothing — a broken engine in which nothing ever fires would pass the vacuity check trivially.
The two satisfiable configs are the control: they demonstrate the machinery *can* find a witness,
which is what makes the absence of one in `Vacuous_ForbiddenApproval` informative.

## Why this exists

AgentCore's temporal policies — written in **Dogwood**, a Cedar superset — decide using the history
of a session rather than the current request alone. From the announcement's own limitations:

> temporal conditions do not currently support the powerful automated reasoning analysis tools that
> Cedar provides

Cedar has symbolic analysis: equivalence, subsumption, satisfiability. Temporal policies have none
of it. So Dogwood **enforces** a policy on the session that happens, and nothing checks that the
policy set means what its author intended across the sessions that could happen. That second thing
is model checking.

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

```
TemporalPolicy                   SATISFIABLE
Vacuous_ForbiddenApproval        VACUOUS
RequestGated_SurvivesForbid      SATISFIABLE
```

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

## What is modelled

Enough MFOTL to pose the question honestly:

| | |
|---|---|
| **metric** | `Window` — a bounded look-back, standing for `within 1h` |
| **first-order** | the correlation `hist[i].stock = req.stock`. Not "some approval happened" but "an approval for **this** stock". A propositional temporal logic cannot express that join, and it is the whole reason the logic is first-order |
| **past-time** | history only. An authorizer decides *now*, from what has already happened — you cannot gate a permit on a future obligation without blocking |

The agent is not modelled: it attempts any request at any time, and `ApproveSale` may return either
verdict. Both are behaviours, so a result holds whatever the agent and the approver do — the same
stance every other spec here takes.

## What this does not establish

- **It is not a model of Dogwood, and it models two layers at once.** Dogwood the *language* has no
  fixed event vocabulary — its grammar says "event kinds are author-defined, not a fixed set —
  `request` / `response` are merely the conventional ones", and a schema marks one of them the
  `decision event`. `error` is not a Dogwood concept at all: it is **AgentCore's** convention for
  recording a denied action. `Policies.tla` holds the schema-declared vocabulary to keep the two
  visibly separate, but every finding here is about the service convention, not the language.
- **The `error` rule is confirmed by the engine, not by the corpus.** Across all 521 cases in
  `tests/passing/temporal_only/corpus`, `::error` appears in **zero** policies and **zero** traces,
  so for a long time the finding rested on the devguide alone. It no longer does: the built engine
  judges traces we construct, and it agrees — see [below](#the-engine-judges-traces-the-corpus-never-recorded).
  What that costs is that the check needs a compiled binary, so it skips where the corpus half runs
  anywhere.
- **The differential test covers `DogwoodSemantics.tla`, not this spec.** `formerly within` as read
  here now agrees with the reference implementation on **911 recorded pairs** — see below. What is
  still unchecked is most of what this spec adds on top: the session model and `Granted`. The
  request/response/error recording convention is the exception — the replay harness puts that one
  in front of the engine directly.
- **Bounded sessions.** `MaxAttempts = 3`, each attempt being two events. "Vacuous" here means *no
  session of up to three attempts fires it*. A permit needing a longer setup would be reported vacuous when it is merely deep. Raise
  the bound to trade runtime for confidence; this is the ordinary bounded-model-checking caveat and
  it does not go away.
- **~~One shape of vacuity.~~** Both shapes are now checked. A permit that *matches* but is always
  overridden by a `forbid` grants nothing either, and a condition-satisfiability check cannot see
  it — the condition is satisfiable, the permit is inert. `Granted` separates matched from granted,
  and [`overridden_permit.dw`](../../../tests/policies/overridden_permit.dw) exercises it. Mutation-checked: drop the
  `Allowed` guard from `Granted` and that file reports live.
- **Nothing about the rest of the policy.** Time-based conditions, `count`/`sum` aggregations,
  `since within`, entity tags and multi-hop session propagation are all unmodelled.


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

### The other corpus: whole policies, not constructs

The regression corpus is written to test an engine, so each case isolates one construct. That
makes it excellent evidence about *semantics* and poor evidence about the question a user
actually asks, which is **"would this work on my policy"**. Dogwood's `dogwood-docs/examples/`
answers that one: whole policies written to show someone how to use the language.

```bash
python tests/strands/dogwood_examples.py
```

```
86 examples, 49 with a trace and expected output

checked   37 of 49 runnable examples (76%)
  AGREE
```

**76%, and the remaining 24% is almost entirely a wall rather than a backlog:**

| refused | why |
|---|---|
| 11 | calls an information provider (a Rhai script) |
| 1 | a custom event kind with a renamed scope bind |

**An information provider is permanently out of scope, and refusing is the correct answer rather
than a gap.** It is a sandboxed Rhai script, so a verdict depending on one is not a function of the
policy and the trace at all; there is nothing for any model to be right about, and a checker that
guessed would be worse than one that declines.

The eleventh joined that column by being read properly rather than by anything changing. A
`when guardrails { … }` clause was refused as "an evaluation mode we do not model" — but the
language guide says three times that `guardrails { E }` is **transparent sugar for `when { E }`**,
carrying no semantics and "retained only for surface compatibility". So the tag is now dropped and
the body parsed as ordinary Cedar, and the one example using it refuses for what is actually in it:
`Strings::Matches(...)`, a provider. Same verdict, true reason.

So the honest denominator is not 49. **Of the 38 examples that can be modelled at all, 37 are —
97%**, and the last needs a custom event kind with a renamed scope bind. Both framings are true and
the first is the one to quote, because a user pointing this at a policy set full of providers really
will get refusals.

Two conventions differ from the unit corpus, and either would misalign every verdict silently:
the oracle is the CLI's `ALLOW`/`DENY` rather than `true`/`false`, and "time point N" counts
**decisions** here where it **indexes the trace** there. The harness keys on the `@N` timestamp,
which means the same thing in both.

#### Macros, and why they were worth doing

The first measurement put macros and providers at ten each, which looked like a coin toss and was
not. Macros are a **purely syntactic** expansion, so doing them moved 10 examples and 1 corpus case
from refused to agreeing — 43% to 63% in one change, the largest single jump this subset has had.

The two rules that matter are stated in `extension/temporal/grammar.pest`, and both would have been
guesses otherwise:

| sigil | meaning |
|---|---|
| `?p` | a value parameter — *"the call-site argument is spliced literally"* |
| `$t` | a fresh binder — *"replaced with a gensym at every expansion"* |

So expansion is token substitution, done **before** parsing. That ordering is the whole trick:
splicing into the token stream means every construct the parser already knows keeps working inside
a macro body for free, and a macro expanding to something unsupported refuses for the reason the
*expansion* gives rather than for whatever the call site happened to look like.

`$t` gensyms **per expansion, not per definition** — two calls to the same macro in one policy must
not share a binder, or the second would capture the first's timepoints.

Coming with them is the **injection operator**, which is the genuinely surprising piece:

```
def temporal same_session(?w, ?s) {
    formerly within ?w (?s{ __drupe.session.id: context.__drupe.session.id })
};
```

`?s{ ... }` *refines the predicate the caller passed*, forcing a field onto an event the caller
never mentioned — here a same-session correlation, onto a policy whose author wrote nothing about
sessions. It is the macro-level echo of the schema-pin finding above: **a policy's meaning is not in
its own text**, and this is a second, independent mechanism that can reach in and change it. Merging
is just concatenation of binds; if an injection names a field the caller already bound differently,
the conjunction is unsatisfiable, which is the right answer and needs no special case.

One thing here is followed rather than verified. Splicing an argument's **tokens** can re-associate
an expression where splicing its parse tree would not — `?n < 100` with `?n` = `a && b` is the
standard hazard. The grammar says literal, so literal is what matches the engine, but **no case in
either corpus distinguishes the two readings**. This rests on the reference implementation's stated
behaviour, not on evidence, and is written down because that is exactly the kind of thing that
otherwise becomes an assumption nobody remembers making.

#### A refusal message is the product

When the answer is "I will not check this", the reason is the whole of what the tool delivers.
These messages used to name the token the parser tripped over, which was true and useless:

```
before                                  after
comparison operator '::'                policy calls the information provider Lists::Allowed,
                                          which runs a script -- its result is not a function
                                          of the policy or the trace
comparison operator 'context'           policy uses an if/then/else expression
expected '::', got '('                  policy calls the macro recently_logged_in()
unlexable at '["VIOLENCE", "HATE"])'    policy calls the information provider Content::Filter
```

Writing them required reading every policy that produces one, and that is how the third row was
found: four cases reported a missing namespace separator, and all four were **macro calls** —
not a diagnosis anyone would have reached from the token. A message that guesses is worse than
one that is vague, because it sends someone to fix the wrong thing.

**That row is why this section exists.** Those four cases are now *supported*, and they were
reachable only because the message was rewritten to name the feature. The bad message hid the size
of the opportunity, not merely the diagnosis: a bucket labelled `expected '::', got '('` reads like
a parser bug worth an afternoon, where `calls a macro` reads like a feature worth doing — and it was
the largest one available.

Each refusal carries a coarse `kind` alongside its specific message, because once a message
names the provider, counting messages puts every name in its own bucket and the summary stops
summarising.

#### Rule attribution: right answer, or right reason?

Every expected output in the examples corpus carries more than a verdict:

```
@0   (time point 0): ALLOW  [rules: 0]
@100 (time point 1): DENY   [rules: 1]
@200 (time point 2): DENY
```

`[rules: N]` is Cedar's **determining policies**, and it is emphatically not "the policies that
matched". At `@100` above *both* policies match — an unconditional permit and a forbid — and only
the forbid is listed. Determining means: the matching forbids when any forbid matches, the matching
permits otherwise, and nothing at all when the deny is by default. The third line has no list
because nothing matched; that absence is itself a claim.

So the verdict is an oracle for **what** was decided and the attribution is an oracle for **why**.
A model can reach the right verdict through the wrong rule, and until now nothing here could tell
those apart. `Determining` computes it from the same `hit` set `Decide` already builds, and
`CaseAgrees` checks it wherever the oracle records it — the unit corpus records only `true`/`false`,
so the conjunct is vacuous there by construction.

**It found no disagreement.** All 31 examples agree on attribution as well as verdict. That is worth
stating plainly rather than dressing up: this did not uncover a bug in the model.

**What it did was close a hole in the evidence**, and that hole was real:

| | |
|---|---|
| decisions with an attribution checked | 124 |
| of those, **not forced by the verdict alone** | **10** |

With a single permit and no forbid, ALLOW can only mean that permit fired and DENY can only mean
nothing matched — the attribution is arithmetic, not evidence. It carries information only when an
ALLOW has several permits to choose between, or when a DENY could be *either* a forbid firing *or*
nothing matching. Ten decisions out of 124, and pretending otherwise would be the same overstatement
the refusal messages were guilty of.

Those ten are not evenly spread, and where they land is the point. **Two examples expect DENY at
every single decision**:

```
forbid_large_except_amzn          3 decisions, all DENY
forbid_read_transfers_over_1000   5 decisions, all DENY
```

A model that denied unconditionally — one where no policy ever matches anything — agrees with both
of those perfectly. They were being counted as evidence while establishing nothing whatsoever about
the forbid's condition. Running exactly that broken model against exactly those two examples:

```
honest model, both checks          PASS
deny-everything, VERDICTS only     PASS   <- the old check
deny-everything, WITH attribution  FAIL   <- the new one
```

Eight of the ten unforced decisions are in those two examples. Attribution is what makes
`when { shares > 100 } unless { stock == "AMZN" }` checkable at all when the verdict never varies.

**Mutation-checked, like the operators.** Replacing `Determining` with the most plausible wrong
reading — that `[rules: N]` lists everything that matched, dropping the forbid-override — turns the
run red. It is caught by one decision, in one example, out of 31.

Because the check's worth rests entirely on that count of 10, the harness prints it and the suite
asserts a floor on it. A change that emptied the rule sets would otherwise leave every run still
reporting AGREE.

#### `like`, and a claim that was wrong

TLA+ defines strings as sequences, and **TLC supports enough of that to match a glob**. The
matcher is `LikeMatches` in `DogwoodSemantics.tla`: ordinary backtracking over `Len` and `SubSeq`.

This section previously said the opposite — that TLA+ "has no string operations" and a string
"cannot be indexed or sliced" — and used it to justify deciding patterns in Python before TLC ran.
Half of that was false. What TLC does not support is applying a string as a **function**:

```
Len("hello")           = 5
SubSeq("hello", 1, 2)  = "he"
"hello"[1]             -> A non-function (a string) was applied as a function
```

So a string can be sliced but not indexed, and a character is read as `SubSeq(s, i, i)`. Lamport's
[errata](../../../reference/books/current-tools.pdf) §2.2.2 documents the enhancement for `\o` and
`Len`; that `SubSeq` also works was established by running TLC, as was the fact that its warning
about `Len` misbehaving on backslash escapes does not reproduce for any escape this project emits.

**The correction matters beyond the claim.** Precomputation was exact, so nothing gave a wrong
answer — but it put `like`'s meaning in a Python helper while every other operator's meaning is in
the spec, differentially validated against the reference implementation. The examples corpus
happened to check that helper; the vacuity checker did not, so a wrong matcher would have made
vacuity quietly wrong with no oracle. Now the artifact the differential validates is the artifact
vacuity uses.

The pattern rules are Cedar's, read off `parser/mod.rs::build_pattern`: unescaped `*` is a wildcard
matching any run of characters, `\*` is a literal asterisk, other escapes follow the string
grammar. A wildcard is not a character, so a pattern reaches TLC as a sequence of `[wild, c]`
records rather than as a string with a reserved character a policy could then never match.

**`sell_like_a_prefix` is a real check.** Its trace holds `AAPL`, `AMZN` and `MSFT`, and the
expected verdicts are ALLOW, ALLOW, **DENY** — a pattern read as matching everything disagrees on
the third.

##### Inventing a value the pattern matches

The differential has a trace, so the field's values are given. The vacuity checker has none: it
synthesises a domain from the literals a policy names, and a pattern names none. So each `like`
contributes its own — one string it matches and one it does not. Both are needed: without a match
the guard can never be true and everything behind it reports VACUOUS; without a non-match, "the
guard failed" is unreachable.

Per-pattern witnesses are right for one pattern and wrong for two on a field:

```
when { context.input.stock like "A*" && context.input.stock like "*L" }
```

`"AAPL"` satisfies both, so the permit is live — but the witnesses are `"A"` and `"L"`, neither
satisfies the other, and the first version of this **reported VACUOUS**. A working rule declared
inert, the same species as the string-valued output field found earlier.

Because TLC evaluates the real pattern, **an invented candidate can never make a policy falsely
live** — it can only fail to be found. That asymmetry is what makes searching safe, so the checker
constructs `"AL"` from what the two patterns literally require and the permit stays live.

When the search comes up empty the checker **refuses**, and `like_impossible.dw` is that case:
nothing starts with both `A` and `B`, so VACUOUS is the *correct* verdict and it declines to give
it. At that point "no such string exists" and "the search was not clever enough" are
indistinguishable, and reporting VACUOUS on a hunch tells someone to delete a rule. Deciding it
properly needs glob intersection, which no policy in either corpus requires — **the regression
corpus uses `like` zero times**.

#### A bare predicate, and asking the engine instead of guessing

`when temporal { formerly within 1h Login{...} && !Logout{...} }` — the second conjunct carries no
temporal operator at all. It is grammatically fine; what it *means* the grammar does not say.

The one example that uses it cannot settle the question, and says so itself: its README notes that
the decision event is always a `Read`, so `!Logout` is trivially true there and the verdict is
driven entirely by the `formerly` beside it. **Agreeing with that example would have been evidence
about `formerly`.** Taking the reading from a prose comment and calling the agreement confirmation
is the exact move this spec exists to avoid.

The built engine is a live oracle, so it was asked. Three constructed traces, pinning the reading
from three directions:

| policy | verdict |
|---|---|
| bare predicate names the decision's own action, bind matches | **ALLOW** |
| names a *different* action — and the trace contains one | **DENY** |
| names its own action, bind does not match | **DENY** |

The middle row is the discriminating one: under a "search the whole trace" reading it would have
allowed. So a bare predicate is an anti-join **at the decision's own timepoint** — the same `at`
term an unwrapped aggregate body already uses.

Then the recorded corpus confirmed it independently: **four unit-corpus cases** that had been
refused for this now translate and agree, and their expected verdicts were produced by the engine
long before any of this. The probe said what the reading was; the corpus said it was right.

#### The shipped presets, which the corpus does not cover

Dogwood ships four event schemas in `configuration/event-schemas/`, selected at deploy time. They
are deployment postures, not fixtures, and each changes what every policy means. We accept three of
the four with the right partition key; `custom-kinds` is refused for the feature it exists to show.

The corpus exercises one pin *shape*: `pin callerPrincipal` (16 cases) and a nested `__drupe` leaf
(3). The shipped `session-pinned` preset — `pin sessionId = context.sessionId`, one flag from the
default — appears in **none** of the 521.

So it was validated against the engine instead. `tests/policies/session_gate.dw` says only "permit
a Trade if this principal was approved within the hour", and replayed unchanged:

| | verdict |
|---|---|
| same session, `session-pinned` | ALLOW |
| **other session, `session-pinned`** | **DENY** |
| other session, `unpinned` | ALLOW |

Same policy, same trace, opposite verdicts — decided by a deployment flag the policy cannot see.
That is the schema-pin finding in the form a user will actually meet it, and all three are now
standing scenarios in `dogwood_replay.py`.

#### Checking under the schema you deploy

`anchor check` takes `--event-schema` now. Without it every answer assumes the **unpinned** reading,
which is not the shipped default, and the tool says so rather than leaving it implicit:

```
no --event-schema given, so every answer below assumes the UNPINNED reading
  (global trace). The shipped DEFAULT partitions by principal, under which a rule
  reported live here may never fire.
```

Wiring it in found a crash that had been latent since the checker was written. A scope bind —
`callerPrincipal: principal`, the ordinary "same principal did it" — killed TLC, because the
synthesized events carried no `session` field and `BindHolds` reads one for every scope bind. No
fixture had used a scope bind, so nothing had ever exercised it. `scope_bind.dw` does now.

**The partition itself is represented but inert, and that is worth stating plainly.** Measured
across `formerly`- and `previous`-gated policies, `pinned`, `unpinned` and no-schema give identical
verdicts. Vacuity asks whether *some* session fires; a partition only removes candidate events, and
any witness it removes has an all-same-caller equivalent that survives. Add that every synthesized
caller may perform every action, and a policy cannot be vacuous-under-pinning here. Making it bite
is a change to how sessions are generated, not to how schemas are read.

#### Ordering on a decimal, which we had wrong

The temporal sublanguage has a specification — `dogwood-docs/guide/04-temporal-expressions.md` —
and our reading of it had been assembled from the corpus and the grammar instead. A pass against
the prose found **23 of its 27 constructs already parse**, and one that parsed *and answered
wrongly*.

Ordering comparisons require both sides to resolve to integers; a decimal "resolves but fails the
integer conversion and yields false". Our `CmpHolds` ordered decimals by their scaled value, so

```
formerly within 1h Score::response{ output.score: s } && s > decimal("0.5")     score = 0.9
```

was TRUE for us and is FALSE for the engine — a gate opening that should stay shut. **No corpus
case compares a decimal with an ordering operator**, so none of the 919 agreeing pairs touched it.
Twelve guards across `CmpHolds`, `Cmp2Holds` and `CmpVarHolds` are integers-only now, and
`order_decimal.dw` pins it against the live engine in `dogwood_replay.py`.

The fixture took two attempts, which is the part worth keeping. `s > 0` against a decimal column
fails the *kind* check before the ordering guard is reached, so the first version passed with and
without the fix — a regression test pinning nothing. Only a decimal on both sides discriminates.

### How `count` was decoded

Corpus case 0254 is the Rosetta stone. Four identical transfers, and:

```
exists (n: Long). ((count for (t: Timepoint).
    where (formerly within 1h (Transfer::request{...} && tp(t)))) == n && n >= 3)
```

Expected verdicts are `true, true, false, false`. That only works if `count` counts **distinct
assignments to the bound variables** — here timepoints, via `tp(t)` — and if the request being
authorized counts itself. Both fall straight out of the flip on the third transfer.

Nothing is built or run for *this* harness — the expected outputs are recorded, so the corpus is
data. (The replay harness below does build the CLI, under the checks in the reference ledger.)
Either way no network is touched and no credentials exist.

**The refusal count matters as much as the agreement count.** 53 cases are outside the modelled
subset and are refused rather than approximated, because a translator that quietly mishandles a
construct yields a disagreement it cannot attribute.

The subset was widened on 2026-09-11, from **654 pairs / 320 cases** to **911 pairs / 468 cases**,
by adding seven constructs:

| construct | example | cases |
|---|---|---|
| a parenthesised left operand of `since` | `!(Login::response{..}) since within 1h Sync::request{..}` | 13 |
| a comparison on the request's own context | `formerly within 1h (Login::request{..} && context.input.amount > 100)` | 24 |
| an aggregate body with **no** temporal wrapper | `count for (t: Timepoint). where (Login::request{..} && tp(t))` | 36 |
| an event schema that **pins** a scope field | `pin callerPrincipal: principalType(A) = principal` | 17 |
| a pin on a nested reserved leaf | `__drupe: { pin session_id: String = context.__drupe.session_id }` | 3 |
| a pin on a context field | `pin tenant_id: String = context.tenant_id` | 1 |
| an aggregate body written **without parentheses** | `sum a for (a: Long). where Transfer::request{ input.amount: a }` | 8 |

Three of them needed **no new semantics at all**, which is worth knowing before reaching for the
evaluator. The parentheses one was not a missing feature at all — `aggregate()` did
`self.expect("(")` unconditionally, so our parser was narrower than the grammar and two whole
refusal buckets were our own strictness. The `since` one was purely the parser: `DogwoodSemantics` already carried `left` and
`leftNeg`, and `unary()` had simply committed to reading `!(` as a negated group before anything
looked for the `since` after it. And `1122_pin_disagree_denies_despite_author_literal` — an author
literal that contradicts a pin — falls straight out of partitioning, with no rule of its own.

## How the constructs were chosen, which is the transferable part

Not by size. Each refusal bucket was first scored by whether its cases have a `true` **anywhere**
in their expected output, because a case whose every verdict is `false` is nearly worthless as
evidence: a reading that matches nothing passes it identically. The six above scored 13/13, 22/24,
24/36, and all of the pin cases.

**`0178_agg_no_temporal_counts_current_tp` is the trap that makes the test worth running.** It
*states* the rule in its own comment — *"Without a temporal wrapper on the body, the aggregation
sees only same-tp events"* — and every one of its verdicts is `false`, so it cannot tell that
reading apart from one that never matches. Implementing from it would have been taking the corpus
author's word and calling it verification.

`0062_count_exact` settles it instead, and only because every `*.dw` in a case forms **one policy
set** — so it tests `n == 2` and `n == 0` together:

| decision | Logins at that timepoint | count | matches | expected |
|---|---|---|---|---|
| @0 Login | the Login itself | 1 | neither | false |
| @4 Alert | none | **0** | `n == 0` | **true** |
| @12 Alert | none | **0** | `n == 0` | **true** |

Counting the whole history gives 3 at @12 where the answer needs 0. A timepoint is a trace
**index**, not a timestamp — the corpus prints `@12 (time point 8)` for one event — so "same tp" is
the decision event's own index.

**Every construct is mutation-checked against its most plausible wrong reading**, not against an
arbitrary break:

| construct | mutation | what it would have meant |
|---|---|---|
| `since` left operand | ignore `leftNeg` | `!A since B` read as `A since B` |
| context comparison | `>` reads as `>=` | an off-by-one on a threshold |
| no-wrapper aggregate | `at` searches `1..upto` | counting the whole history |
| pins | treat every pin as universal | granting isolation a partial pin did not earn |
| pins | drop partitioning, keep conjuncts | the reading that passes every existential case |
| non-scope pins | key on principal instead | session/tenant partitioning silently wrong |

All six turn the run red. The third and fourth matter most: each is what a reasonable
implementation would do first.


**Widening stopped, then resumed for a different reason.** The first stop was right on the
evidence: more corpus cases were telling us little new about the *semantics*. What changed is the
metric. Once the deliverable is "point the checker at a policy somebody's pipeline generated", the
question is no longer how much evidence a case adds but whether a real policy can be checked at
all — **coverage, not evidence**. The same work, better justified.

The parser now accepts **488 of 521** corpus policies, and `anchor check` checks **every one of
them**. Refusals fell from 123 cases to 53, and the pairs from 786 to 911.

What that second push added was mostly *syntax the language has and we did not*: integer, decimal
and entity-reference literals in binds; a bare `action` scope; comparisons with either operand
first, between two request fields, or against a bound variable; an aggregate compared without the
`exists` wrapper and written four ways; general existential quantification; a negated atom; and a
`since` whose left operand is a group. None of it changed what the modelled operators mean.

**53 cases still stand refused.** Of the 30 schema-bearing cases, 21 now pass and the nine
that remain contain **no pin at all** -- they are in the corpus for renamed reserved fields, deep
paths and injected slots, each a separate feature. The rest: macro calls and parameter sigils,
custom event kinds, deeper `__drupe` paths, `since` nested inside an aggregate body, `count`/`sum`
bodies written without parentheses, comparisons against something other than a literal, and ten
`Long` values outside TLC's integer range, which no amount of modelling will fix.

**`SessionRotation` checks a real Dogwood policy, end to end.** Neither the decision nor the
policy is written in that spec any more:

```
rotation_*.dw ──> translator  ──> RotationPolicies.tla ──┐
                                                           ├──> TLC checks the properties
                             SessionRotation.tla ──────────┘
```

The policy is [`rotation_aggregate.dw`](rotation_aggregate.dw) and
[`rotation_approval.dw`](rotation_approval.dw) — Dogwood text — translated by the same parser whose
reading agrees with the reference implementation on 914 corpus cases, and evaluated by the same
`DogwoodSemantics!Decide`. Even the cap is lifted from the policy text into `Cap`, so the property
and the rule cannot disagree about what the limit is.

Two earlier versions each hand-wrote one half of this and each time the finding rested on something
unchecked: first a hand-rolled `SumTrades`, then policy records nobody had compared against the
Dogwood text in their own comment. The only thing the spec still asserts on its own is the
adversary.

**The wiring is live, demonstrated by editing the policy text rather than the model:**

| `.dw` edit | `Cap` | rotation | control |
|---|---|---|---|
| baseline | 3 | VIOLATED | HOLDS |
| `n > 3` becomes `n > 100` | **100** | **HOLDS** | HOLDS |
| `forbid` becomes `permit` | 3 | VIOLATED | **VIOLATED** |

`RotationPolicies.tla` is generated and checked in — which is what lets the spec tests run in CI
without a venv — so `src/translator/dw_to_tla.py --check` regenerates and compares, and the suite fails on drift.

### What it caught on the first run

Two disagreements, and both were ours.

A case whose `event.dwschema` declares:

```
pin callerPrincipal: principalType(A) = principal
```

The schema comment says what that does: *"The policy never writes `callerPrincipal`; the pin injects
it, so the correlation cannot be bypassed by a directly-written predicate."*

In that case's second trace, **bob logs in claiming to be alice**, then alice reads. The written
condition matches — `input.user` correlates alice to alice — and Dogwood denies anyway, because the
pin requires the login's `callerPrincipal` to equal the reader's `principal`.

**A policy's meaning is not determined by its own text.** Reading the `.dw` and ignoring the schema
is exactly the silent mishandling this harness exists to prevent, so schema-bearing cases are now
refused. Modelling pins would be a real extension, and it is not done.

The harness is mutation-checked: removing the metric bound from `TermHolds` turns the run red.


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
