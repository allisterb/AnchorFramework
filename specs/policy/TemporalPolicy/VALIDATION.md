# Validating the Dogwood semantics

The detail behind [Checked against the reference implementation](README.md#checked-against-the-reference-implementation):
how `DogwoodSemantics.tla` was held against Dogwood's own corpora, how the constructs it models
were chosen, and what that caught. The [README](README.md) has the summary and the findings.

## The other corpus: whole policies, not constructs

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

`anchor check` takes `--event-schema`, the schema a policy set is deployed under. Without one it uses
**Dogwood's own default reading, `callerPrincipal` pinned**. Until 0.1.3 Anchor's default was the
opposite, unpinned, which answered about a deployment nobody gets unless they ask for it.
`--unpinned` checks global-trace semantics, for a deployment whose schema has no universal pin, and
`--pinned` states the default explicitly. Only one of the three may be given. They work on a
directory audit too, whose report states the reading in every run, and the MCP tool takes the same
choice as `pinned`. With no schema the tool still says which reading it used, because a default the
reader does not know was chosen for them is one they cannot question:

```
no --event-schema given, so every answer below uses Dogwood's own default
  reading: callerPrincipal pinned on every kind, so a temporal condition sees
  only the requesting principal's events. Pass --event-schema for your
  deployment's real one, or --unpinned if it has no universal pin.
```

**Every witness replay is handed the same reading, as a file.** `dogwood replay` gets
`pinned.dwschema` or `unpinned.dwschema`, copied from Dogwood's shipped schemas, so the engine
confirms a counterexample under the reading the model found it under. Before 0.1.3 it was given no
schema whenever the caller had none, so the engine fell back to its own pinned default and confirmed
a model built unpinned: two readings, agreeing only because every session had one principal.

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

## How `count` was decoded

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
