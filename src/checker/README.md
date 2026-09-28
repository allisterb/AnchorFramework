# `checker` — what follows from a policy

[`translator`](../translator) decides what a policy set *says*. This decides what follows from it, by
asking TLC questions the policy text cannot answer about itself.

**Vocabulary.** A *policy* is one `permit` or `forbid` statement and a `.dw` file is a *policy set*,
which is Dogwood's term (see
[TemporalPolicy](../../specs/policy/TemporalPolicy/README.md) for the sources). This README says
*rule* for one policy, as AWS's own Dogwood posts often do, because every verdict here is about one
statement's effect on the whole set. A *session* is one AgentCore
[*policy session*](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html):
the history of related requests a temporal condition can see. Every verdict here ranges over all
sessions up to `--attempts` attempts long (3 by default), which is the bound a VACUOUS verdict is
provisional on.

Also reachable as `anchor check`, which finds the interpreter and the Anchor tree itself and
passes the exit code straight through — see [`Anchor.CLI`](../Anchor.CLI).

```bash
python src/checker/properties.py tests/policies/docs_trading.dw
python src/checker/properties.py a.dw --against b.dw
python src/checker/properties.py firewall.dw --property firewall.tla
python src/checker/properties.py firewall.dw --describe    # what a --property module may name
python src/checker/properties.py big.dw --smoke 1000      # random walk, for a model too big to exhaust
```

## The smoke tier, and why its polarity is backwards from every other smoke test

`--smoke N` runs TLC as a random walk of N behaviours instead of exhausting the state space. The
usual reason to do that is a sound NEGATIVE: find a counterexample and the spec is broken, find none
and you have learnt nothing.

**Here it is the other way round.** This checker already reads TLC backwards -- a violation is the
GOOD outcome, the witness proving a rule does something. So a random walk gives a sound POSITIVE:

| smoke says | means | sound? |
|---|---|---|
| `live` | a witness was found, so the rule really does change a verdict | **yes** -- a witness is a witness however it was reached |
| `unknown` | this walk did not reach a session where the rule matters | it is **not a verdict**, and never means the rule is inert |

So a smoke run can report `live`, and **can never report VACUOUS, REDUNDANT or DEAD**. Those three
are claims of ABSENCE, a random walk cannot establish absence, and each of them tells someone to
delete a rule.

**What it is for is not speed on the cases exhaustive already handles.** Exhaustive search stops at
the first violation, so a live rule is found quickly either way. It is for models where exhaustive
does not finish at all -- which is exactly what raising `--attempts` to gain confidence in a VACUOUS
verdict produces. There, smoke turns "no answer about anything" into "these rules are definitely
live, and the rest I could not settle".

## Two kinds of property, and the difference is who can state it

| | |
|---|---|
| **derivable** | statable from the policy alone. We write these for you |
| **intentional** | only the author knows it. You write it, we check it |

### Derivable — the three that come in the box

| question | verdict | meaning |
|---|---|---|
| Can this permit ever grant? | **VACUOUS** | it never fires — whatever it was meant to allow is unreachable. A bug, not untidiness. |
| Is this rule load-bearing? | **REDUNDANT** | it fires, but another permit always would too. |
| | **DEAD** | this forbid never denies anything the rest of the set would have allowed. |
| Do two versions ever disagree? | `--against` | a session they decide differently, or a bounded no. |

They are one question underneath — *does deleting or changing this rule change some verdict* — and
every answer is either **a witness session** or **a bounded no**. The bound is printed with the
answer, because a bounded no is not a proof and should not read like one.

There is no fourth derivable check. Without being told what a policy is *for*, there is nothing
further to say about it.

### Intentional — `--property`

```bash
python src/checker/properties.py firewall.dw --property firewall.tla
```

A property module is TLA+ of your own extending the generated `PolicyUnderTest`, stating what the
policy is supposed to mean. It needs a companion `.cfg` naming its invariants — naming them is
deliberate, because a property nobody listed is a property nobody checked.

**One mechanism, not two.** `Vacuity.tla` is itself a property module extending the same generated
records; the only difference is that it explores sessions and a per-request claim does not.

#### Why the derivable checks are not enough

`firewall_open.dw` drops a `forbid` and widens a permit, letting the whole internet connect on port
22. The built-in checks do not miss it silently — they report

```
REDUNDANT permit #1   it fires, but another permit always would too
```

which is **true**, and whose advice — delete the redundant rule — shrinks the policy set and leaves
the hole exactly where it was. The redundancy is a *symptom* of the over-broad permit, and a check
that cannot know what the policy set was for cannot tell you which of the two rules is the mistake.

The property can, because it was told:

```
BROKEN  Invariant OutsideIsRefused is violated by the initial state:
        req = [port |-> [k |-> "n", v |-> 22], origin |-> [k |-> "s", v |-> "external"]]
```

#### State the requests your claim is about

`PolicyUnderTest` deliberately offers **no** `Inputs`. The request space derivable from a policy
comes from that policy's own literals, so a claim about a value it never mentions ranges over no
such request — it holds **vacuously** and reports success having looked at nothing.

That is not hypothetical: it is what the first version of `firewall.tla` did. Drop the `forbid` and
`"external"` leaves the vocabulary, so `OutsideIsRefused` passed against the broken policy. Two
lines fix it, and they belong to the claim:

```tla
Requests == {[port |-> Num(p), origin |-> Str(o)] : p \in {22, 2222}, o \in {"local", "external"}}
```

#### And that failure is now detected rather than described — `anchor explain`

The paragraph above is a warning that was only ever enforced by whoever read it. `explain` reads
the module instead, and says what each claim forbids and how many of the states it ranges over its
condition even applies to:

```bash
python src/checker/explain.py examples/aws1/TrustDecay10.tla
anchor check policy.dw --property TrustDecay10.tla --explain   # the same, before the verdict
```

```
  LosesWriteAfter10m
     says      whenever gap is greater than 10 * Minute (= 600), then the policy REFUSES it
     forbids   gap is greater than 10 * Minute (= 600), and yet the policy GRANTS it
     applies   to 3 of the 6: gap = 840, gap = 960, gap = 1800
```

`applies to NONE` is the vacuous claim above, caught before TLC starts, and it exits **4** — the
same code `--mutation-score` uses for the same defect found the expensive way.

**It runs no model checker**, which is the point: the checkpoint the literature puts at the
property-formulation boundary is only useful if it is instant. It is a small recursive-descent
reader over the fragment these modules state claims in, and it computes the state space and the
condition — ordinary arithmetic over values the module itself names. It does **not** evaluate
`Decide`; that is the whole authorization semantics, TLC is about to do it properly, and a second
implementation here would disagree silently.

So the two gates catch different things and neither replaces the other:

| | catches | costs |
|---|---|---|
| `explain` | a claim whose condition no state satisfies; one true by its own arithmetic; a `.cfg` naming an invariant that does not exist; claims defined but never listed | milliseconds, reading |
| `--mutation-score` | a claim that holds of the policy *and of every broken version of it* — including a tautology about the decision, which reading cannot see | one TLC run per mutant |

**`--mutants N` takes a prefix, so the ORDER of the mutants decides which rules ever get broken.**
They are generated breadth first — every rule's deletion, then every inversion, then the dropped
conditions — so the default cap of 8 still touches every rule of a 7-rule policy set. Grouped by rule,
as they were, those 8 went entirely to rules 1–3 and **rules 4–7 were never damaged**: a property
about a later rule survived every mutant tried and was told it "is not constraining this policy at
all", which is false and is the worst thing this gate can say. Measured on
`examples/aws2/agent-policy.dw`: a property about `initiate_transfer` (rules 4 and 5) caught **0 of
the first 8** and **4 of all 21**, every one of the four on rules 4 and 5.

**Every mutation removes or narrows a permission**, which bounds what this gate can prove. A rule
deleted, a permit typed as a forbid, a condition dropped so a forbid matches more — all of them
make the policy refuse *more*. So a property whose claims only say what must be **refused** survives
every one of them however carefully it names its values, and needs at least one claim about what
must be **allowed** before this gate means anything. The complaint says so.

## The answer this must never get wrong

A false **VACUOUS** tells someone to delete a rule that works. Everything else the checker can get
wrong wastes a reader's time; that one changes their policy.

It has been got wrong twice, and both are pinned as fixtures rather than described:

- `tests/policies/string_output.dw` — every output field was modelled as boolean, so a gate on a
  string output could never match. Eight output binds in Dogwood's own corpus compare against a
  string.
- `tests/policies/like_impossible.dw` — where the checker cannot construct a value satisfying two
  `like` patterns at once, it **refuses** rather than reporting VACUOUS, because "no such string
  exists" and "the search was not clever enough" are indistinguishable from in here.

The rule that falls out: when this cannot decide, it refuses and names what is missing. A refusal
is a correct answer; a false VACUOUS is not.

## What is this value? — `--eval`

```bash
python src/checker/properties.py policy.dw --property Claim.tla --eval "TradeAllowed(960)"
```

Evaluates a TLA+ expression in the policy's own semantics and prints the value. About two seconds,
and it checks nothing — it answers what a value IS, which is otherwise a question you have to write
an invariant and run a check to find out.

With `--property` that module's definitions are in scope, which is where it earns its keep:

| | |
|---|---|
| `Session(960)` | the events, with their times — the commonest thing to have wrong is the units |
| `TradeAllowed(960)` | `TRUE`. The policy's decision for that session, with no invariant anywhere |
| `<<TradeAllowed(900), TradeAllowed(901)>>` | `<<FALSE, TRUE>>` — a temporal window's boundary located in one call |

Without it, the generated vocabulary is the context: `Policies`, the field domains, the constructors.

It works by generating a module whose `ASSUME PrintT(expr)` makes TLC evaluate the expression once
during initialisation, with markers around the value so it can be lifted out of TLC's preamble —
the technique used by will62794's `tlaplus_repl`, noted in the reference ledger. **SANY cannot do
this**: it parses and resolves and never evaluates, and in-process TLC is not viable under IKVM.

**A value is not a verdict.** That the policy grants one session says nothing about the others.

## Is it even a Dogwood policy? — `--syntax`

This checker reads a **subset** of Dogwood, so its refusals carry two meanings under one message:
*the construct is outside the subset*, or *the policy is broken*. Those need opposite responses —
one is a limitation to work around, the other is a bug to go and fix — and our parser cannot tell
them apart, because it is the thing whose coverage is in question.

```bash
python src/checker/properties.py policy.dw --syntax
```

```
SYNTAX ERROR in policy.dw -- the reference implementation will not parse it.
Nothing below was checked.

× unexpected token `{`, expected comparison operator
   ╭─[4:9]
 5 │ │               AgentCore::Action::"execute_buy"{
   · ╰──── unexpected token `{`, expected comparison operator
```

**A syntax error is not a verification finding.** It is the reason a run produces none, so it exits
**2** — no verdict — never 0.

`--syntax` asks *first*, which is what you want on a policy somebody has just edited. On the
**refusal path the engine is consulted anyway**, without the flag: by then the run has already
failed, 35ms is nothing against telling somebody the wrong thing about why, and the result is that
a broken file never sits there looking like a limitation of this tool:

```
REFUSED: policy.dw is outside the modelled subset
  expected '::', got '{'

AND IT IS NOT VALID DOGWOOD EITHER. The reference implementation refuses to parse
this file, so the refusal above is not a limit of the modelled subset -- there is a
syntax error in the policy. `dogwood check-parse` says: ...
```

A policy that parses cleanly draws no such comment — a second opinion on a healthy file is noise,
and would train a reader to ignore it on the file that needs it. Both need the `dogwood` binary,
and both say so and carry on without it.

## The counterexample, in Dogwood — `--witness`

A broken claim ends in a TLA+ state:

```
BROKEN  Invariant LosesWriteAfter15m is violated by the initial state:
    gap = 960
```

Correct, and in the wrong language. The input was a `.dw` file its author wrote and can read; the
output is a variable belonging to a TLA+ module a tool may have drafted, holding a number whose
units are not written down. `--witness` carries it back:

```bash
python src/checker/properties.py policy.dw --property TrustDecay.tla --witness
```

```
  LosesWriteAfter10m
      TLC found      gap = 960
      which is       @1 interact_advisor::response  @961 execute_trade::request
      dogwood says   ALLOW at t=961  -- confirms the finding
      so             with gap = 960, the Dogwood engine ALLOWS this session at t=961, where
                     `LosesWriteAfter10m` says your policy must REFUSE it
```

Two steps, worth keeping apart:

1. **What session is `gap = 960`?** The property module says: `Session(gap) == << Interaction(1),
   Trade(1 + gap) >>`. That recipe is already parsed by [`explain.py`](explain.py), so evaluating
   it at 960 gives concrete events with times.
2. **Ask Dogwood.** Those events render as a `.log` trace, a Cedar schema is generated from the
   policy's own vocabulary, and `dogwood replay` judges it.

**The second step is a different kind of evidence from anything else here.** Every other verdict
rests on our TLA+ semantics being a faithful reading of Dogwood — established by differential
testing against 914 recorded pairs, which is a very good argument and not a proof. A replay is not
an argument: it is the reference implementation answering the question. A confirmed finding no
longer depends on us being right about the language.

And a **disagreement is a bug in Anchor**, reported as one and never quietly dropped.

Which way round a claim reads is decided by evaluation, not by syntax: the claim is evaluated with
the decision assumed each way, and the assumption that makes it *false* is what the policy did. If
neither does, this reader and TLC disagree about what a counterexample is, and it says so and
claims nothing rather than guessing.

### The evidence is portable

`--keep DIR` writes everything the engine consumes into `DIR/witness/`, so the finding can be
checked by someone who does not have this checkout — or does not trust it:

| file | |
|---|---|
| `<policy>.dw` | **copied, not referenced.** A directory pointing at a policy elsewhere stops being evidence the moment it is moved or the policy is edited — and editing it is exactly what somebody does after reading the finding |
| `generated.cedarschema` | built from the policy's own actions and field types. `replay` requires one, and hand-writing it would be a second description of the policy to keep in step with the first |
| `<Claim>.log` | the session, in Dogwood's trace syntax |
| `<schema>.dwschema` | the event schema, when the check used one |
| `README.md` | what each file is, the exact command, and how to read the result |

```bash
cd traces/07-trust-decay-TrustDecay10/witness
dogwood replay --policy-schema generated.cedarschema --trace LosesWriteAfter10m.log 07-trust-decay.dw
```
```
@961 (time point 0): ALLOW  [rules: 0]
```

The command in that README is the command that produced the verdict — same builder, so the two
cannot drift — and [the harness runs it](../../tests/strands/witness_replay.py) and compares its
output to what the finding claims. A README telling somebody to run something else is worse than
none: they run it, get a different answer, and the disagreement is ours.

**The event schema travels with the counterexample**, and that is a correctness matter rather than
tidiness. A universal pin changes what history a temporal predicate can see, so replaying a witness
TLC found under a pinned reading against the engine's default answers a question nobody asked —
confidently, with the reference implementation's authority behind it.

`--witness` needs the `dogwood` binary, which is not in the repo. Without it the session is still
printed — only the engine's confirmation is missing.

## `ANCHOR_TLC_JAVA_OPTS`, and why it has no default

Extra JVM flags for every TLC run, honoured by both the Python runner and `TLCProcess`. Unset, so
a run started by hand gets the JVM's own defaults.

The one worth knowing about is `-XX:TieredStopAtLevel=1`, which stops the C2 optimising compiler.
Whether it helps depends entirely on how big the search is, and the crossover was measured:

| | default | `-XX:TieredStopAtLevel=1` | |
|---|---|---|---|
| one run, 40 states | 1.90s | 1.59s | 16% faster |
| **eight at once**, 40 states | 8.92s | 4.68s | **1.9× faster** |
| one run, 960k states | 3.72s | 4.00s | 8% slower |
| one run, 6.7M states | 12.17s | 18.67s | **53% slower** |

A short run never lasts long enough for C2's compilation to pay for itself, and several at once are
several JVMs each burning cores on optimisation they finish before benefiting from. A long search
is the opposite case, and there the optimised code is most of the throughput.

So there is no value right for both, and choosing one globally would be choosing it for the runs
that care least. Every policy in this repo checks in about a second — but yours might be the big
one, so the default is the JVM's. The **test suite** sets it, in
`tests/*/anchor.runsettings`, because there every model is bounded small by construction and six
classes compete for the machine; it took the suite from 8m46 to 3m30 together with the class split.

Set it yourself if you are running many small checks at once — a directory sweep, or CI.

## Why it is not part of `translator`

Translating a policy and reasoning about one are different jobs with different failure modes, and
the MCP server will want them separately — "what does this policy say" is a question you can answer
without ever starting a JVM.

The seam between them is `PolicyUnderTest.tla`, which [`translator/policy_module.py`](../translator/policy_module.py)
generates. Everything here extends it, and so does every property anyone writes.
