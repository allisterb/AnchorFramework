---
title: Writing a property module
description: How to state what a policy is SUPPOSED to mean, and the trap that makes such a claim pass having checked nothing.
---

# Writing a property module

There are two kinds of claim about a policy, and the difference is who is able to state it.

| | |
|---|---|
| **derivable** | statable from the policy alone. `CheckPolicy` answers these already: VACUOUS, REDUNDANT/DEAD, and `against` for a diff |
| **intentional** | only the author knows it. You write it, Anchor checks it |

The three built-ins would all pass a firewall policy that let the whole internet in, because "every
rule fires and none is redundant" is true of that policy too. An intentional claim is the other
kind: *SSH from the local range is permitted, and every external source is denied.*

You state one as a TLA+ module passed to `CheckPolicy`'s `property` argument.

## The workflow

Six phases, in order. Each says what went wrong when it was skipped. The evidence is about 45 drafted
modules from recorded runs: once the mechanics were right, most failures came from phases 1 and 4.

1. **Decide the cases from the REQUIREMENT, before looking at the policy.** In words: which sessions
   must be allowed, which must be denied, and where the boundary sits. Do not first evaluate what
   the policy does and then describe it. A claim derived from the policy restates it, and passes
   whatever the policy says. One drafter called `evaluate` eight times to learn the policy's
   behaviour, then wrote claims matching that behaviour, and the reviewer rejected them.
2. **Read the vocabulary.** Action names, field names, and which fields live in an event's `input`
   and which in its `output`. A policy that reads the `input` of an earlier response is not
   satisfied by a value placed in its `output`. One draft did that, and passed every gate while
   testing nothing.
3. **Build the sessions.** Use plain-valued variables, times in seconds, and values the policy never
   names. **Put every prerequisite in the session**: a policy that needs `verify_identity` first
   denies every transfer in a session without it, and then every refusal claim holds without
   testing anything.
4. **Write claims in BOTH directions.** At least one claim must say a specific session is
   **allowed**: a fully compliant one, with every prerequisite present, that the requirement plainly
   intends to permit. Without it, every claim says "must refuse". No mutation that *removes* a
   permission can break such a module, and a policy that refuses everything passes it. 12 of the
   recorded drafts were refusal-only, and 8 of those died at mutation scoring.
   Keep the allowed claim to that one session, not a rule. "X requires Y" means *without Y, refused*.
   It does not mean *with Y, always allowed*, since other rules may still deny. The reviewer rejects
   a claim that turns one into the other.
5. **Check the mechanics.** Does it compile, does it evaluate, and when something is odd, what IS
   that value? See the tools below. This is seconds; the real check is minutes.
6. **Read it back before answering.** Read the `forbids` line and the `applies` count (see "Read what
   it forbids"). If the `forbids` line does not describe something you would object to, the claim is
   not your requirement.

## The loop, and the tool for each step

Writing one is four steps, and each has a tool. The two in the middle cost about a second; only the
last costs minutes, so reaching for it first is the expensive mistake.

The tools have two names: one over MCP, and one when Anchor's own drafting pipeline runs you. Use
whichever set you were given.

| | over MCP | in the drafting pipeline | |
|---|---|---|---|
| what may I name? | **`DescribePolicyModule`** | already in your prompt, as "the vocabulary" | the vocabulary, from the policy's own text, plus a skeleton that runs |
| does it compile? | **`CheckPropertyModule`** | **`check_module`**, which also evaluates the module once | SANY against that policy's generated vocabulary. ~1s. A misspelled operator gets you a line and a column instead of a failed model-checking run |
| **what IS this value?** | **`EvaluateExpression`** | **`evaluate`** | evaluates a TLA+ expression in the policy's own semantics. ~2s |
| does it say what I meant? | **`ExplainPropertyModule`** | **`what_it_forbids`** | what each claim FORBIDS, in English, and how many of its states its condition applies to. Milliseconds |
| **can it fail at all?** | `--decision-probe` | run for you after you answer | does the policy ever ANSWER differently over these states? Seconds. A policy that refuses everything the property names makes every refusal claim hold having tested nothing |
| do the claims hold? | **`CheckPolicy`** with `property` | run for you after you answer | the actual check. Minutes |

**`EvaluateExpression` is the one to reach for when something is behaving oddly**, because most of
what goes wrong here is a value being other than you assumed — the units of a window, what a
session actually contains, whether a set has the member you think. With `property` set, that
module's own definitions are in scope:

```
Session(960)                            the events, with their times
TradeAllowed(960)                       TRUE   — the policy's decision, with no invariant anywhere
<<TradeAllowed(900), TradeAllowed(901)>>  <<FALSE, TRUE>>   — a window's boundary, in one call
```

**A value is not a verdict.** That the policy grants one session says nothing about the others.
Use it to understand, then check.

`CheckPropertyModule` needs the **policy** as well as the module, and the reason is worth knowing:
a property module `EXTENDS PolicyUnderTest`, which is generated *from the policy*, so "does it
compile" is only answerable against a particular one.

## Start with `DescribePolicyModule`

Do not write one from memory. The module you extend — `PolicyUnderTest` — is **generated from the
policy**, and its vocabulary is lifted from that policy's own text. Action names, field names and
domains differ per policy and cannot be guessed.

`DescribePolicyModule` returns all of it, plus a skeleton module that already elaborates and runs.
Edit the skeleton's claim rather than starting from a blank file.

## Scalars are tagged, and this is the mistake that wastes the most runs

**A tagged value is a RECORD, not the thing inside it.** `Num(22)` is `[k |-> "n", v |-> 22]`, with
the kind in `.k` and the value in `.v`. Which form a comparison needs depends on the operator:

```tla
req.origin = Str("external")    \* right: = and # compare two tagged values
req.origin = "external"         \* WRONG. Dies at run time: "Attempted to check equality of
                                \*        record: ..." -- a record cannot be compared with a string

input.amount.v <= 2500          \* right: <, <=, >, >= and arithmetic need the number, .v
input.amount <= 2500            \* WRONG. Dies at run time: "The first argument of <= should
input.amount <= Num(2500)       \* WRONG too, the same way: <= is applied to two records
```

Both wrong ordering forms die with the same message, "The first argument of <= should be an integer,
but instead it is: [k |-> ...]". `Num(1) <= Num(2)` fails; `Num(1).v <= 2` is `TRUE`.

They compile — SANY resolves names, not record fields — so the module passes every cheap check and
then dies during evaluation, having established nothing. **This is the single commonest reason a
drafted module produces no verdict**: seven attempts across the recorded sweeps. An earlier version
of this article gave `input.amount <= Num(2500)` as the right form, and drafters followed it.

The simplest way to avoid all of it is in the next section: keep your own variables plain, compare
them as plain integers (`amount <= 2500`), and tag them only where they go into an event.

| constructor | for |
|---|---|
| `Str(x)` | a string |
| `Num(x)` | an integer |
| `Bool(x)` | `TRUE` / `FALSE` |
| `Addr(a, b, c, d)` | an address — **four octets**, because TLC cannot hold one as a 32-bit number |

**The exception, and it is not optional either:** `Ev` takes PLAIN values for its action, kind and
time — `Ev("execute_trade", "request", NoFields, NoFields, 900)`. The constructors are for field
values *inside* the input and output records, and nowhere else.

### And a VARIABLE must never range over tagged values

This is the other half of the same rule, and on its own it has cost more runs than anything else
in this file. **Let your variables hold plain values and tag them where they are used.**

```tla
VARIABLES gap, verified, account                   \* RIGHT
Init == /\ gap      \in {60, 960}
        /\ verified \in {TRUE, FALSE}
        /\ account  \in {1, 2}
...     [account |-> Num(account), ...], [verified |-> Bool(verified), ...]

VARIABLES verified, account                        \* WRONG — dies at run time
Init == /\ verified \in {Bool(TRUE), Bool(FALSE)}
        /\ account  \in {Num(1), Num(2)}
```

The wrong version compiles, and then TLC stops while computing the initial states with:

```
Error: Attempted to check equality of integer 1 with non-integer:
FALSE
Error: TLC was unable to fingerprint.
```

`Num(1)` is `[v |-> 1, k |-> "n"]` and `Bool(FALSE)` is `[v |-> FALSE, k |-> "b"]`, so somewhere
below this an integer is being compared with a boolean. **The message names neither your variables
nor the tagging**, which is why this is worth memorising rather than deriving: it looks like an
arithmetic bug and is a typing one.

*Reproduced three times in live sessions on the same requirement, and fixed each time by moving the
tags from the `Init` domains to the point of use, changing nothing else.* **The mechanism is NOT
established.** A minimal reconstruction — two variables, one `Num` domain and one `Bool` domain —
evaluates perfectly well, so the obvious explanation is not the whole of it. What is pinned is the
behaviour: `tests/policies/tagged_session.tla` is the real module, kept because a theory of it did
not reproduce.

Your claims then read more naturally too — `verified /\ account = 2` rather than
`verified = Bool(TRUE) /\ account = Num(2)`.

## Three rules that stop the usual syntax failures

- **Bound every quantifier.** `\A x \in Requests : P(x)`, never `\A x : P(x)` — TLC cannot
  enumerate an unbounded one.
- **`\A` pairs with `=>`, `\E` pairs with `/\`.** A `\A` over a conjunction is almost always meant
  as an implication, and asserts something far stronger than intended.
- **Write the helper predicate first, then wrap it.** Not one long formula:

  ```tla
  IsExternalGrant(r) == r.origin = Str("external") /\ Grants(r)
  OutsideIsRefused   == ~IsExternalGrant(req)
  ```

### TLA+ that drafts have got wrong

Each of these ended a recorded draft.

```tla
LET e == Ev("verify_identity", "response", NoFields, NoFields, 1) IN e   \* ==, never = in a LET
{x.v : x \in S}                     \* map: an expression, then the set it ranges over
{x \in S : x.v > 100}               \* filter: a variable in a set, then a condition
{x.v : x \in {y \in S : y.v > 100}} \* both: nest them; {e : x \in S : P} does not parse
D!Decide(s, Policies, 2, AllValues) \* an instance's operator takes !, never D.Decide
~Allowed(s)                         \* Decide returns a BOOLEAN; it has no .permit field
x.v                                 \* a tagged value's fields are .k and .v, never .val
```

- **There is no `SUM`.** Do not compute totals in a claim. Build the session with amounts whose total
  you already know, and state the claim about that session.
- **A module needs its header and its terminator.** The first line is `---- MODULE Name ----` and
  the last is `====`. The name must be the one you were given.

**Do not `EXTENDS TLC`.** It breaks evaluation of the policy semantics on any policy that both joins
across value kinds and carries an aggregate — the module compiles and then fails with
"Attempted to check equality of string ... with non-string". Nothing in a property module needs it.

## The trap: there is deliberately no `Inputs`

`PolicyUnderTest` does not offer a set of all requests to quantify over, and that is on purpose.

A request space derived from the policy's own literals cannot test a claim about a value the policy
never mentions. Delete the `forbid` that names `"external"` and the value vanishes from the
vocabulary — so a claim like `OutsideIsRefused` would range over **nothing**, hold vacuously, and
report success having examined nothing. That is worse than failing.

So **state the requests your claim is about**, including values the policy never names:

```tla
Origins == {"local", "external"}
Ports   == {22, 2222}
Requests == {[port |-> Num(p), origin |-> Str(o)] : p \in Ports, o \in Origins}
```

The description's `plusOneValueThePolicyNeverNames` tells you the model already admits one such
value internally — but it is not writable, so it is no substitute for naming your own.

## The shape

```tla
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>
Grants(input) == D!Decide(<<Request("Connect", input)>>, Policies, 1, AllValues)

VARIABLE req
Init == req \in Requests
Next == UNCHANGED req
Spec == Init /\ [][Next]_req

LocalSshIsAllowed == (req.port = Num(22) /\ req.origin = Str("local")) => Grants(req)
OutsideIsRefused  == (req.origin = Str("external")) => ~Grants(req)
```

One request is chosen nondeterministically and held, so a violation's counterexample **names the
request** that breaks the claim rather than merely reporting that one exists.

There is no session in *that* example: "what does this policy decide for this request" is not a
temporal question, so there is no state machine beyond holding one request still.

## A claim about TIMING needs a session, and you build it yourself

Most Dogwood policies are temporal, and a claim like *"after fifteen minutes without an approval,
writes are refused"* cannot be stated about one request. Build the session by hand with
`Ev(action, kind, input, output, time)` and ask the evaluator about one event of it:

```
Interaction(t) == Ev("interact_advisor", "response", NoFields, NoFields, t)
Trade(t)       == Ev("execute_trade", DecisionKind, NoFields, NoFields, t)

Session(gap)      == << Interaction(1), Trade(1 + gap) >>
TradeAllowed(gap) == D!Decide(Session(gap), Policies, 2, AllValues)   \* 2 = the trade

Minute == 60
Gaps   == {1, 10 * Minute, 16 * Minute}

VARIABLE gap
Init == gap \in Gaps
Next == UNCHANGED gap
Spec == Init /\ [][Next]_gap

LosesWriteAfter15m == (gap > 15 * Minute) => ~TradeAllowed(gap)
```

**`time` IS IN SECONDS.** The evaluator compares it against a window width directly, so a claim
about a 15-minute window needs events 900 apart — not 2. This is the thing that catches people
out, because the built-in questions explore sessions whose events are one second apart: a long
window can never age out there, and only a hand-built trace can put a decision on the far side
of one.

**`Ev` takes PLAIN values for its action, kind and time**, as above — `Ev("execute_trade",
"request", NoFields, NoFields, 900)`, never `Ev(Str("execute_trade"), …, Num(900))`. The tagged
constructors (`Str`, `Num`, `Bool`, `Addr`) are for field **values inside** the input and output
records, and nowhere else. Tagging the action or the time is the commonest way to get a module
that will not compile.

The index passed to `Decide` is which event of the trace is being decided, counting from 1. It is
almost always the last.

**State the gaps you mean**, as above. The same trap applies as with requests: a set derived from
the policy's own windows would contain only the numbers it already mentions, and a claim about
"ten minutes" would then range over nothing and pass having checked nothing.

## The `.cfg` is not optional

A companion `.cfg` must name the specification and every invariant:

```
SPECIFICATION Spec
INVARIANT LocalSshIsAllowed
INVARIANT OutsideIsRefused
```

Naming them is deliberate: **a property nobody listed is a property nobody checked.**

## Read what it forbids before you check it

A property is checked against exactly what it says. If what it says is not what you meant, the run
is just as rigorous, passes just as convincingly, and establishes nothing — and no verdict
downstream can tell you that happened, because every check below the property is faithful to it.

So read the claim back before running anything -- `ExplainPropertyModule` over MCP, or:

```bash
anchor explain TrustDecay10.tla
```

```
  LosesWriteAfter10m
     says      whenever gap is greater than 10 * Minute (= 600), then the policy REFUSES it
     forbids   gap is greater than 10 * Minute (= 600), and yet the policy GRANTS it
     applies   to 3 of the 6: gap = 840, gap = 960, gap = 1800
```

**The `forbids` line is the one to disagree with.** It is the only thing the claim can catch. If it
does not describe something you would object to seeing happen, the check will pass without testing
your intention.

**The `applies` line is the size of the experiment.** A claim shaped `A => B` tests nothing at all
in any state where `A` is false, so a condition that matches two of six states is a claim about two
states. `applies to NONE` is reported as a finding — the claim would hold, TLC would say so, and it
would have examined nothing:

```
  applies   to NONE of the 2 states
  !!        NOTHING THIS CLAIM RANGES OVER CAN BREAK IT ...
```

That is the same defect as a vacuous permit, in the property instead of the policy, and it is the
commonest way a property module ends up worthless. It happens most often exactly where the trap
above describes: a claim about a value the request set never presents.

`--explain` on a check prints the same thing first, so the claim is read before its verdict is:

```bash
anchor check policy.dw --property TrustDecay10.tla --explain
```

What it will **not** catch is a tautology about the decision itself — `Grants(r) \/ ~Grants(r)`
holds whatever the policy says, and the explainer does not evaluate `Decide`, deliberately. That
one is caught by `--mutation-score`, which breaks the policy and checks that the property notices.
The two are complementary; neither replaces the other.

## Then ask whether the policy ever ANSWERS differently

```bash
anchor check policy.dw --property Intent.tla --decision-probe
```

```
  decision over this module's states: CONSTANT
      the policy REFUSES every request this property names: `Grants(req)` is false in
      every state the module ranges over ...
```

**This is the commonest way a drafted property comes back worthless, and the hardest to see by
reading.** The claims are well formed, their conditions match states, the module compiles — and the
policy refuses every single request the property names, so every claim about a refusal holds without
testing anything. Five drafted properties out of five failed this way on one real policy set.

The usual cause is a **missing prerequisite**. A policy set that requires `verify_identity` before
`initiate_transfer` denies every transfer in a session that has no verification in it — so the rule
your property is actually about is never reached. Put the prerequisite event in the session:

```tla
Session(gap) == << Verify(1), Transfer(1 + gap) >>     \* not just << Transfer(t) >>
```

Two TLC runs, seconds. `VARIES` is a precondition for checking the claims, not a verdict on them;
`CONSTANT` exits 4, the same code as a property that catches no mutant, because it is the same
defect found earlier and more cheaply.

## When it goes wrong

| you see | it means | do this |
|---|---|---|
| `The first argument of <= should be an integer, but instead it is: [k \|-> ...]` | `<`, `<=`, `>` or `>=` applied to a tagged value | compare the number inside: `x.v <= 2500` |
| `Attempted to check equality of record: [k \|-> ...] with non-record` (or `of string`/`of integer` ... `with non-string: [k \|-> ...]`) | a tagged value compared with a plain one by `=` or `#` | tag both sides, `s = Str("a1")`, or compare the insides |
| `Attempted to check equality of integer 1 with non-integer: FALSE` | a VARIABLE ranging over tagged values | plain values in `Init`, tagged where they go into an event |
| `Attempted to check equality of string ... with non-string` on a policy that joins and aggregates | `EXTENDS TLC` | remove it |
| `Unknown operator: Decide` | no `D == INSTANCE DogwoodSemantics WITH Cases <- << >>` line | add it, and call `D!Decide` |
| decision over the module's states: **CONSTANT** | the policy answers every named session the same way, usually from a missing prerequisite | put the prerequisite event in the session |
| `applies to NONE` | the claim's condition is never true in any state it ranges over | range over values that make it true |
| survives every mutant ("holds of every broken version") | every claim says "must refuse", or none can tell the policy from a broken one | add the allowed claim from phase 4 |
| the reviewer says the claim describes the policy, not the requirement | the claims were written from the policy's behaviour | go back to phase 1 |

## Reading the result

A violation means the policy does **not** mean what your property says it means, and the state
printed is the request that breaks it. A clean run means every claim held over every request you
named — and says nothing about requests you did not name.

## Do not report a violation as `gap = 960`

That is the answer in the wrong language. The person who owns the policy wrote `.dw` and may never
have seen the module; a state naming a TLA+ variable, in units nobody wrote down, is something they
cannot check — and a finding nobody can check is a finding nobody acts on.

Pass `witness` and the same finding comes back in theirs:

```
  LosesWriteAfter10m
      TLC found      gap = 960
      which is       @1 interact_advisor::response  @961 execute_trade::request
      dogwood says   ALLOW at t=961  -- confirms the finding
      so             with gap = 960, the Dogwood engine ALLOWS this session at t=961, where
                     `LosesWriteAfter10m` says your policy must REFUSE it
```

It works out which session the counterexample stands for — from your module's own `Session(gap)` —
renders it as a Dogwood trace, and puts it to `dogwood replay`. **That verdict is the reference
engine's, not ours.** Quote it in preference to the TLA+ state: it names a concrete value the
author can try against their own policy, and it does not ask them to trust our reading of Dogwood.

If the two ever disagree, say so plainly. A disagreement is a defect in Anchor, not a finding about
the policy, and reporting it as the latter would be wrong.
