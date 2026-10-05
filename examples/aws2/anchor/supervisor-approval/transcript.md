# Agent transcript

`agent-policy.dw`: every LLM call this run made, in order -- the drafter with its tool calls, the reviewer and the reporter.

*Generated 2026-10-04 17:26 UTC by `src/agent/pipeline.py`. Tool calls and their full replies are included: the prose is a claim, and the tool output is the evidence for it.*

## draft round 1

**Asked:**

> The module MUST be named exactly `SupervisorApproval`, so its first line is:
>     ---------------------------- MODULE SupervisorApproval ----------------------------
> Do not copy the module name from the skeleton below; it is a different name.
> 
> How to write one:
> 
> ---
> title: Writing a property module
> description: How to state what a policy is SUPPOSED to mean, and the trap that makes such a claim pass having checked nothing.
> ---
> 
> # Writing a property module
> 
> There are two kinds of claim about a policy, and the difference is who is able to state it.
> 
> | | |
> |---|---|
> | **derivable** | statable from the policy alone. `CheckPolicy` answers these already: VACUOUS, REDUNDANT/DEAD, and `against` for a diff |
> | **intentional** | only the author knows it. You write it, Anchor checks it |
> 
> The three built-ins would all pass a firewall policy that let the whole internet in, because "every
> rule fires and none is redundant" is true of that policy too. An intentional claim is the other
> kind: *SSH from the local range is permitted, and every external source is denied.*
> 
> You state one as a TLA+ module passed to `CheckPolicy`'s `property` argument.
> 
> ## The workflow
> 
> Six phases, in order. Each says what went wrong when it was skipped. The evidence is about 45 drafted
> modules from recorded runs: once the mechanics were right, most failures came from phases 1 and 4.
> 
> 1. **Decide the cases from the REQUIREMENT, before looking at the policy.** In words: which sessions
>    must be allowed, which must be denied, and where the boundary sits. Do not first evaluate what
>    the policy does and then describe it. A claim derived from the policy restates it, and passes
>    whatever the policy says. One drafter called `evaluate` eight times to learn the policy's
>    behaviour, then wrote claims matching that behaviour, and the reviewer rejected them.
> 2. **Read the vocabulary.** Action names, field names, and which fields live in an event's `input`
>    and which in its `output`. A policy that reads the `input` of an earlier response is not
>    satisfied by a value placed in its `output`. One draft did that, and passed every gate while
>    testing nothing.
> 3. **Build the sessions.** Use plain-valued variables, times in seconds, and values the policy never
>    names. **Put every prerequisite in the session**: a policy that needs `verify_identity` first
>    denies every transfer in a session without it, and then every refusal claim holds without
>    testing anything.
> 4. **Write claims in BOTH directions.** At least one claim must say a specific session is
>    **allowed**: a fully compliant one, with every prerequisite present, that the requirement plainly
>    intends to permit. Without it, every claim says "must refuse". No mutation that *removes* a
>    permission can break such a module, and a policy that refuses everything passes it. 12 of the
>    recorded drafts were refusal-only, and 8 of those died at mutation scoring.
>    Keep the allowed claim to that one session, not a rule. "X requires Y" means *without Y, refused*.
>    It does not mean *with Y, always allowed*, since other rules may still deny. The reviewer rejects
>    a claim that turns one into the other.
> 5. **Check the mechanics.** Does it compile, does it evaluate, and when something is odd, what IS
>    that value? See the tools below. This is seconds; the real check is minutes.
> 6. **Read it back before answering.** Read the `forbids` line and the `applies` count (see "Read what
>    it forbids"). If the `forbids` line does not describe something you would object to, the claim is
>    not your requirement.
> 
> ## The loop, and the tool for each step
> 
> Writing one is four steps, and each has a tool. The two in the middle cost about a second; only the
> last costs minutes, so reaching for it first is the expensive mistake.
> 
> The tools have two names: one over MCP, and one when Anchor's own drafting pipeline runs you. Use
> whichever set you were given.
> 
> | | over MCP | in the drafting pipeline | |
> |---|---|---|---|
> | what may I name? | **`DescribePolicyModule`** | already in your prompt, as "the vocabulary" | the vocabulary, from the policy's own text, plus a skeleton that runs |
> | does it compile? | **`CheckPropertyModule`** | **`check_module`**, which also evaluates the module once | SANY against that policy's generated vocabulary. ~1s. A misspelled operator gets you a line and a column instead of a failed model-checking run |
> | **what IS this value?** | **`EvaluateExpression`** | **`evaluate`** | evaluates a TLA+ expression in the policy's own semantics. ~2s |
> | does it say what I meant? | **`ExplainPropertyModule`** | **`what_it_forbids`** | what each claim FORBIDS, in English, and how many of its states its condition applies to. Milliseconds |
> | **can it fail at all?** | `--decision-probe` | run for you after you answer | does the policy ever ANSWER differently over these states? Seconds. A policy that refuses everything the property names makes every refusal claim hold having tested nothing |
> | do the claims hold? | **`CheckPolicy`** with `property` | run for you after you answer | the actual check. Minutes |
> 
> **`EvaluateExpression` is the one to reach for when something is behaving oddly**, because most of
> what goes wrong here is a value being other than you assumed — the units of a window, what a
> session actually contains, whether a set has the member you think. With `property` set, that
> module's own definitions are in scope:
> 
> ```
> Session(960)                            the events, with their times
> TradeAllowed(960)                       TRUE   — the policy's decision, with no invariant anywhere
> <<TradeAllowed(900), TradeAllowed(901)>>  <<FALSE, TRUE>>   — a window's boundary, in one call
> ```
> 
> **A value is not a verdict.** That the policy grants one session says nothing about the others.
> Use it to understand, then check.
> 
> `CheckPropertyModule` needs the **policy** as well as the module, and the reason is worth knowing:
> a property module `EXTENDS PolicyUnderTest`, which is generated *from the policy*, so "does it
> compile" is only answerable against a particular one.
> 
> ## Start with `DescribePolicyModule`
> 
> Do not write one from memory. The module you extend — `PolicyUnderTest` — is **generated from the
> policy**, and its vocabulary is lifted from that policy's own text. Action names, field names and
> domains differ per policy and cannot be guessed.
> 
> `DescribePolicyModule` returns all of it, plus a skeleton module that already elaborates and runs.
> Edit the skeleton's claim rather than starting from a blank file.
> 
> ## Scalars are tagged, and this is the mistake that wastes the most runs
> 
> **A tagged value is a RECORD, not the thing inside it.** `Num(22)` is `[k |-> "n", v |-> 22]`, with
> the kind in `.k` and the value in `.v`. Which form a comparison needs depends on the operator:
> 
> ```tla
> req.origin = Str("external")    \* right: = and # compare two tagged values
> req.origin = "external"         \* WRONG. Dies at run time: "Attempted to check equality of
>                                 \*        record: ..." -- a record cannot be compared with a string
> 
> input.amount.v <= 2500          \* right: <, <=, >, >= and arithmetic need the number, .v
> input.amount <= 2500            \* WRONG. Dies at run time: "The first argument of <= should
> input.amount <= Num(2500)       \* WRONG too, the same way: <= is applied to two records
> ```
> 
> Both wrong ordering forms die with the same message, "The first argument of <= should be an integer,
> but instead it is: [k |-> ...]". `Num(1) <= Num(2)` fails; `Num(1).v <= 2` is `TRUE`.
> 
> They compile — SANY resolves names, not record fields — so the module passes every cheap check and
> then dies during evaluation, having established nothing. **This is the single commonest reason a
> drafted module produces no verdict**: seven attempts across the recorded sweeps. An earlier version
> of this article gave `input.amount <= Num(2500)` as the right form, and drafters followed it.
> 
> The simplest way to avoid all of it is in the next section: keep your own variables plain, compare
> them as plain integers (`amount <= 2500`), and tag them only where they go into an event.
> 
> | constructor | for |
> |---|---|
> | `Str(x)` | a string |
> | `Num(x)` | an integer |
> | `Bool(x)` | `TRUE` / `FALSE` |
> | `Addr(a, b, c, d)` | an address — **four octets**, because TLC cannot hold one as a 32-bit number |
> 
> **The exception, and it is not optional either:** `Ev` takes PLAIN values for its action, kind and
> time — `Ev("execute_trade", "request", NoFields, NoFields, 900)`. The constructors are for field
> values *inside* the input and output records, and nowhere else.
> 
> ### And a VARIABLE must never range over tagged values
> 
> This is the other half of the same rule, and on its own it has cost more runs than anything else
> in this file. **Let your variables hold plain values and tag them where they are used.**
> 
> ```tla
> VARIABLES gap, verified, account                   \* RIGHT
> Init == /\ gap      \in {60, 960}
>         /\ verified \in {TRUE, FALSE}
>         /\ account  \in {1, 2}
> ...     [account |-> Num(account), ...], [verified |-> Bool(verified), ...]
> 
> VARIABLES verified, account                        \* WRONG — dies at run time
> Init == /\ verified \in {Bool(TRUE), Bool(FALSE)}
>         /\ account  \in {Num(1), Num(2)}
> ```
> 
> The wrong version compiles, and then TLC stops while computing the initial states with:
> 
> ```
> Error: Attempted to check equality of integer 1 with non-integer:
> FALSE
> Error: TLC was unable to fingerprint.
> ```
> 
> `Num(1)` is `[v |-> 1, k |-> "n"]` and `Bool(FALSE)` is `[v |-> FALSE, k |-> "b"]`, so somewhere
> below this an integer is being compared with a boolean. **The message names neither your variables
> nor the tagging**, which is why this is worth memorising rather than deriving: it looks like an
> arithmetic bug and is a typing one.
> 
> *Reproduced three times in live sessions on the same requirement, and fixed each time by moving the
> tags from the `Init` domains to the point of use, changing nothing else.* **The mechanism is NOT
> established.** A minimal reconstruction — two variables, one `Num` domain and one `Bool` domain —
> evaluates perfectly well, so the obvious explanation is not the whole of it. What is pinned is the
> behaviour: `tests/policies/tagged_session.tla` is the real module, kept because a theory of it did
> not reproduce.
> 
> Your claims then read more naturally too — `verified /\ account = 2` rather than
> `verified = Bool(TRUE) /\ account = Num(2)`.
> 
> ## Three rules that stop the usual syntax failures
> 
> - **Bound every quantifier.** `\A x \in Requests : P(x)`, never `\A x : P(x)` — TLC cannot
>   enumerate an unbounded one.
> - **`\A` pairs with `=>`, `\E` pairs with `/\`.** A `\A` over a conjunction is almost always meant
>   as an implication, and asserts something far stronger than intended.
> - **Write the helper predicate first, then wrap it.** Not one long formula:
> 
>   ```tla
>   IsExternalGrant(r) == r.origin = Str("external") /\ Grants(r)
>   OutsideIsRefused   == ~IsExternalGrant(req)
>   ```
> 
> ### TLA+ that drafts have got wrong
> 
> Each of these ended a recorded draft.
> 
> ```tla
> LET e == Ev("verify_identity", "response", NoFields, NoFields, 1) IN e   \* ==, never = in a LET
> {x.v : x \in S}                     \* map: an expression, then the set it ranges over
> {x \in S : x.v > 100}               \* filter: a variable in a set, then a condition
> {x.v : x \in {y \in S : y.v > 100}} \* both: nest them; {e : x \in S : P} does not parse
> D!Decide(s, Policies, 2, AllValues) \* an instance's operator takes !, never D.Decide
> ~Allowed(s)                         \* Decide returns a BOOLEAN; it has no .permit field
> x.v                                 \* a tagged value's fields are .k and .v, never .val
> ```
> 
> - **There is no `SUM`.** Do not compute totals in a claim. Build the session with amounts whose total
>   you already know, and state the claim about that session.
> - **A module needs its header and its terminator.** The first line is `---- MODULE Name ----` and
>   the last is `====`. The name must be the one you were given.
> 
> **Do not `EXTENDS TLC`.** It breaks evaluation of the policy semantics on any policy that both joins
> across value kinds and carries an aggregate — the module compiles and then fails with
> "Attempted to check equality of string ... with non-string". Nothing in a property module needs it.
> 
> ## The trap: there is deliberately no `Inputs`
> 
> `PolicyUnderTest` does not offer a set of all requests to quantify over, and that is on purpose.
> 
> A request space derived from the policy's own literals cannot test a claim about a value the policy
> never mentions. Delete the `forbid` that names `"external"` and the value vanishes from the
> vocabulary — so a claim like `OutsideIsRefused` would range over **nothing**, hold vacuously, and
> report success having examined nothing. That is worse than failing.
> 
> So **state the requests your claim is about**, including values the policy never names:
> 
> ```tla
> Origins == {"local", "external"}
> Ports   == {22, 2222}
> Requests == {[port |-> Num(p), origin |-> Str(o)] : p \in Ports, o \in Origins}
> ```
> 
> The description's `plusOneValueThePolicyNeverNames` tells you the model already admits one such
> value internally — but it is not writable, so it is no substitute for naming your own.
> 
> ## The shape
> 
> ```tla
> EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest
> 
> D == INSTANCE DogwoodSemantics WITH Cases <- << >>
> Grants(input) == D!Decide(<<Request("Connect", input)>>, Policies, 1, AllValues)
> 
> VARIABLE req
> Init == req \in Requests
> Next == UNCHANGED req
> Spec == Init /\ [][Next]_req
> 
> LocalSshIsAllowed == (req.port = Num(22) /\ req.origin = Str("local")) => Grants(req)
> OutsideIsRefused  == (req.origin = Str("external")) => ~Grants(req)
> ```
> 
> One request is chosen nondeterministically and held, so a violation's counterexample **names the
> request** that breaks the claim rather than merely reporting that one exists.
> 
> There is no session in *that* example: "what does this policy decide for this request" is not a
> temporal question, so there is no state machine beyond holding one request still.
> 
> ## A claim about TIMING needs a session, and you build it yourself
> 
> Most Dogwood policies are temporal, and a claim like *"after fifteen minutes without an approval,
> writes are refused"* cannot be stated about one request. Build the session by hand with
> `Ev(action, kind, input, output, time)` and ask the evaluator about one event of it:
> 
> ```
> Interaction(t) == Ev("interact_advisor", "response", NoFields, NoFields, t)
> Trade(t)       == Ev("execute_trade", DecisionKind, NoFields, NoFields, t)
> 
> Session(gap)      == << Interaction(1), Trade(1 + gap) >>
> TradeAllowed(gap) == D!Decide(Session(gap), Policies, 2, AllValues)   \* 2 = the trade
> 
> Minute == 60
> Gaps   == {1, 10 * Minute, 16 * Minute}
> 
> VARIABLE gap
> Init == gap \in Gaps
> Next == UNCHANGED gap
> Spec == Init /\ [][Next]_gap
> 
> LosesWriteAfter15m == (gap > 15 * Minute) => ~TradeAllowed(gap)
> ```
> 
> **`time` IS IN SECONDS.** The evaluator compares it against a window width directly, so a claim
> about a 15-minute window needs events 900 apart — not 2. This is the thing that catches people
> out, because the built-in questions explore sessions whose events are one second apart: a long
> window can never age out there, and only a hand-built trace can put a decision on the far side
> of one.
> 
> **`Ev` takes PLAIN values for its action, kind and time**, as above — `Ev("execute_trade",
> "request", NoFields, NoFields, 900)`, never `Ev(Str("execute_trade"), …, Num(900))`. The tagged
> constructors (`Str`, `Num`, `Bool`, `Addr`) are for field **values inside** the input and output
> records, and nowhere else. Tagging the action or the time is the commonest way to get a module
> that will not compile.
> 
> The index passed to `Decide` is which event of the trace is being decided, counting from 1. It is
> almost always the last.
> 
> **State the gaps you mean**, as above. The same trap applies as with requests: a set derived from
> the policy's own windows would contain only the numbers it already mentions, and a claim about
> "ten minutes" would then range over nothing and pass having checked nothing.
> 
> ## The `.cfg` is not optional
> 
> A companion `.cfg` must name the specification and every invariant:
> 
> ```
> SPECIFICATION Spec
> INVARIANT LocalSshIsAllowed
> INVARIANT OutsideIsRefused
> ```
> 
> Naming them is deliberate: **a property nobody listed is a property nobody checked.**
> 
> ## Read what it forbids before you check it
> 
> A property is checked against exactly what it says. If what it says is not what you meant, the run
> is just as rigorous, passes just as convincingly, and establishes nothing — and no verdict
> downstream can tell you that happened, because every check below the property is faithful to it.
> 
> So read the claim back before running anything -- `ExplainPropertyModule` over MCP, or:
> 
> ```bash
> anchor explain TrustDecay10.tla
> ```
> 
> ```
>   LosesWriteAfter10m
>      says      whenever gap is greater than 10 * Minute (= 600), then the policy REFUSES it
>      forbids   gap is greater than 10 * Minute (= 600), and yet the policy GRANTS it
>      applies   to 3 of the 6: gap = 840, gap = 960, gap = 1800
> ```
> 
> **The `forbids` line is the one to disagree with.** It is the only thing the claim can catch. If it
> does not describe something you would object to seeing happen, the check will pass without testing
> your intention.
> 
> **The `applies` line is the size of the experiment.** A claim shaped `A => B` tests nothing at all
> in any state where `A` is false, so a condition that matches two of six states is a claim about two
> states. `applies to NONE` is reported as a finding — the claim would hold, TLC would say so, and it
> would have examined nothing:
> 
> ```
>   applies   to NONE of the 2 states
>   !!        NOTHING THIS CLAIM RANGES OVER CAN BREAK IT ...
> ```
> 
> That is the same defect as a vacuous permit, in the property instead of the policy, and it is the
> commonest way a property module ends up worthless. It happens most often exactly where the trap
> above describes: a claim about a value the request set never presents.
> 
> `--explain` on a check prints the same thing first, so the claim is read before its verdict is:
> 
> ```bash
> anchor check policy.dw --property TrustDecay10.tla --explain
> ```
> 
> What it will **not** catch is a tautology about the decision itself — `Grants(r) \/ ~Grants(r)`
> holds whatever the policy says, and the explainer does not evaluate `Decide`, deliberately. That
> one is caught by `--mutation-score`, which breaks the policy and checks that the property notices.
> The two are complementary; neither replaces the other.
> 
> ## Then ask whether the policy ever ANSWERS differently
> 
> ```bash
> anchor check policy.dw --property Intent.tla --decision-probe
> ```
> 
> ```
>   decision over this module's states: CONSTANT
>       the policy REFUSES every request this property names: `Grants(req)` is false in
>       every state the module ranges over ...
> ```
> 
> **This is the commonest way a drafted property comes back worthless, and the hardest to see by
> reading.** The claims are well formed, their conditions match states, the module compiles — and the
> policy refuses every single request the property names, so every claim about a refusal holds without
> testing anything. Five drafted properties out of five failed this way on one real policy set.
> 
> The usual cause is a **missing prerequisite**. A policy set that requires `verify_identity` before
> `initiate_transfer` denies every transfer in a session that has no verification in it — so the rule
> your property is actually about is never reached. Put the prerequisite event in the session:
> 
> ```tla
> Session(gap) == << Verify(1), Transfer(1 + gap) >>     \* not just << Transfer(t) >>
> ```
> 
> Two TLC runs, seconds. `VARIES` is a precondition for checking the claims, not a verdict on them;
> `CONSTANT` exits 4, the same code as a property that catches no mutant, because it is the same
> defect found earlier and more cheaply.
> 
> ## When it goes wrong
> 
> | you see | it means | do this |
> |---|---|---|
> | `The first argument of <= should be an integer, but instead it is: [k \|-> ...]` | `<`, `<=`, `>` or `>=` applied to a tagged value | compare the number inside: `x.v <= 2500` |
> | `Attempted to check equality of record: [k \|-> ...] with non-record` (or `of string`/`of integer` ... `with non-string: [k \|-> ...]`) | a tagged value compared with a plain one by `=` or `#` | tag both sides, `s = Str("a1")`, or compare the insides |
> | `Attempted to check equality of integer 1 with non-integer: FALSE` | a VARIABLE ranging over tagged values | plain values in `Init`, tagged where they go into an event |
> | `Attempted to check equality of string ... with non-string` on a policy that joins and aggregates | `EXTENDS TLC` | remove it |
> | `Unknown operator: Decide` | no `D == INSTANCE DogwoodSemantics WITH Cases <- << >>` line | add it, and call `D!Decide` |
> | decision over the module's states: **CONSTANT** | the policy answers every named session the same way, usually from a missing prerequisite | put the prerequisite event in the session |
> | `applies to NONE` | the claim's condition is never true in any state it ranges over | range over values that make it true |
> | survives every mutant ("holds of every broken version") | every claim says "must refuse", or none can tell the policy from a broken one | add the allowed claim from phase 4 |
> | the reviewer says the claim describes the policy, not the requirement | the claims were written from the policy's behaviour | go back to phase 1 |
> 
> ## Reading the result
> 
> A violation means the policy does **not** mean what your property says it means, and the state
> printed is the request that breaks it. A clean run means every claim held over every request you
> named — and says nothing about requests you did not name.
> 
> ## Do not report a violation as `gap = 960`
> 
> That is the answer in the wrong language. The person who owns the policy wrote `.dw` and may never
> have seen the module; a state naming a TLA+ variable, in units nobody wrote down, is something they
> cannot check — and a finding nobody can check is a finding nobody acts on.
> 
> Pass `witness` and the same finding comes back in theirs:
> 
> ```
>   LosesWriteAfter10m
>       TLC found      gap = 960
>       which is       @1 interact_advisor::response  @961 execute_trade::request
>       dogwood says   ALLOW at t=961  -- confirms the finding
>       so             with gap = 960, the Dogwood engine ALLOWS this session at t=961, where
>                      `LosesWriteAfter10m` says your policy must REFUSE it
> ```
> 
> It works out which session the counterexample stands for — from your module's own `Session(gap)` —
> renders it as a Dogwood trace, and puts it to `dogwood replay`. **That verdict is the reference
> engine's, not ours.** Quote it in preference to the TLA+ state: it names a concrete value the
> author can try against their own policy, and it does not ask them to trust our reading of Dogwood.
> 
> If the two ever disagree, say so plainly. A disagreement is a defect in Anchor, not a finding about
> the policy, and reporting it as the latter would be wrong.
> 
> 
> ---
> 
> The vocabulary for THIS policy:
> 
> ```json
> {
>   "source": "agent-policy.dw",
>   "reading": "no --event-schema given, so every answer below uses Dogwood's own default\n  reading: callerPrincipal pinned on every kind, so a temporal condition sees\n  only the requesting principal's events. Pass --event-schema for your\n  deployment's real one, or --unpinned if it has no universal pin.",
>   "module": "PolicyUnderTest",
>   "actions": [
>     "initiate_transfer",
>     "issue_refund",
>     "request_approval",
>     "verify_identity"
>   ],
>   "kinds": [
>     "request",
>     "response"
>   ],
>   "decisionKind": "request",
>   "inputFields": [
>     {
>       "name": "account",
>       "kind": "integer",
>       "domain": [
>         "Num(1)",
>         "Num(2)"
>       ],
>       "plusOneValueThePolicyNeverNames": false
>     },
>     {
>       "name": "amount",
>       "kind": "integer",
>       "domain": [
>         "Num(499)",
>         "Num(500)",
>         "Num(2500)",
>         "Num(2501)"
>       ],
>       "plusOneValueThePolicyNeverNames": false
>     },
>     {
>       "name": "charge_id",
>       "kind": "integer",
>       "domain": [
>         "Num(1)",
>         "Num(2)"
>       ],
>       "plusOneValueThePolicyNeverNames": false
>     },
>     {
>       "name": "systemNowTime",
>       "kind": "integer",
>       "domain": [
>         "Num(32399999)",
>         "Num(32400000)",
>         "Num(61200000)",
>         "Num(61200001)"
>       ],
>       "plusOneValueThePolicyNeverNames": false
>     }
>   ],
>   "outputFields": [
>     {
>       "name": "approved",
>       "kind": "boolean",
>       "domain": [
>         "Bool(FALSE)",
>         "Bool(TRUE)"
>       ],
>       "plusOneValueThePolicyNeverNames": false
>     },
>     {
>       "name": "verified",
>       "kind": "boolean",
>       "domain": [
>         "Bool(FALSE)",
>         "Bool(TRUE)"
>       ],
>       "plusOneValueThePolicyNeverNames": false
>     }
>   ],
>   "pinKeys": [
>     "principal"
>   ],
>   "rules": [
>     {
>       "index": 1,
>       "effect": "permit",
>       "actions": [
>         "verify_identity"
>       ]
>     },
>     {
>       "index": 2,
>       "effect": "permit",
>       "actions": [
>         "request_approval"
>       ]
>     },
>     {
>       "index": 3,
>       "effect": "permit",
>       "actions": [
>         "issue_refund"
>       ]
>     },
>     {
>       "index": 4,
>       "effect": "permit",
>       "actions": [
>         "initiate_transfer"
>       ]
>     },
>     {
>       "index": 5,
>       "effect": "forbid",
>       "actions": [
>         "initiate_transfer"
>       ]
>     },
>     {
>       "index": 6,
>       "effect": "forbid",
>       "actions": [
>         "issue_refund"
>       ]
>     },
>     {
>       "index": 7,
>       "effect": "forbid",
>       "actions": [
>         "issue_refund"
>       ]
>     }
>   ],
>   "operators": {
>     "Request(action, input)": "one request as the evaluator reads it, at time 1",
>     "Ev(action, kind, input, output, time)": "ONE EVENT AT A CHOSEN TIME AND KIND -- what a claim about a SESSION is built from. `action` and `kind` are PLAIN strings and `time` a PLAIN integer -- Ev(\"trade\", \"request\", NoFields, NoFields, 900), never Str(\"trade\") or Num(900). Tagging is for field VALUES inside the input/output records and nowhere else. `time` is in SECONDS: a claim about a 15m window needs events 900 apart, not two",
>     "NoFields": "an empty input or output record",
>     "D!Decide(trace, Policies, i, AllValues)": "the verdict for event `i` of a trace you built -- a sequence of Ev(...), in time order. This is how a TEMPORAL claim is stated; `Grants` in the skeleton is the one-event shorthand",
>     "Policies": "the rule set, as the sequence Decide evaluates",
>     "AllValues": "every value any field may take -- Decide's last argument",
>     "InputDomain": "[field |-> {values}] for the fields above",
>     "OutputDomain": "[field |-> {values}] for the output fields",
>     "PinKeys": "the fields a universal pin partitions on; empty means global-trace"
>   },
>   "constructors": {
>     "Str(x)": "a string",
>     "Num(x)": "an integer",
>     "Bool(x)": "TRUE or FALSE",
>     "Addr(a, b, c, d)": "an address, FOUR OCTETS -- TLC works in Java ints, so 208.4.4.0 as 3489924096 is not a value it can hold",
>     "Anon": "the anonymous principal/resource/session a per-request claim uses"
>   },
>   "rules_for_writing_one": [
>     "EXTENDS PolicyUnderTest, and instantiate DogwoodSemantics with Cases <- << >>.",
>     "Scalars are TAGGED. Inside an event's record write Num(22), never 22. Compare with = and # against a tagged value (s = Str(\"a1\")), but order the number inside (x.v <= 22): x <= Num(22) fails at run time.",
>     "There is no Inputs. State the requests your claim is about, including values this policy never mentions, or the claim may range over nothing and pass.",
>     "Decide the allowed and denied cases from the requirement BEFORE evaluating the policy. A claim written from the policy's own behaviour restates it.",
>     "Include a claim that one specific, fully compliant session is ALLOWED. A module of refusal claims alone cannot be broken by removing a permission. 'X requires Y' means 'without Y, refused', not 'with Y, always allowed'.",
>     "Put every prerequisite event in the session, and each value where the policy reads it: inputFields in an event's input record, outputFields in its output record.",
>     "The .cfg must name SPECIFICATION Spec and every INVARIANT. A claim nobody listed is a claim nobody checked."
>   ],
>   "skeleton": "---------------------------- MODULE agent_policy ----------------------------\n\\* What agent-policy.dw is SUPPOSED to mean, stated by its author. The three built-in findings\n\\* (VACUOUS, REDUNDANT/DEAD, diff) are the claims statable WITHOUT knowing intent; this is the\n\\* other kind, and only the author can write it.\n\\*\n\\* SAVE THIS AS agent_policy.tla -- TLA+ requires the file name to match the module name, and a\n\\* module name may not contain `-` or `.` or begin with a digit, so it is not always the policy's\n\\* own name.\n\\*\n\\* Check it with:  python src/checker/properties.py agent-policy.dw --property agent_policy.tla\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\n\n\\* The verdict for one request. No session: \"what does this policy decide for this request\" is\n\\* not a temporal question, so there is no state machine beyond holding one request still.\nGrants(input) == D!Decide(<<Request(\"initiate_transfer\", input)>>, Policies, 1, AllValues)\n\n(***************************************************************************)\n(* THE REQUESTS THIS CLAIM IS ABOUT.                                       *)\n(*                                                                         *)\n(* Written out rather than derived from InputDomain, and that is the       *)\n(* point. A space derived from the policy's own literals cannot test a     *)\n(* claim about a value the policy never mentions: delete the rule that     *)\n(* names a value and it vanishes from the vocabulary, so the claim ranges  *)\n(* over nothing and PASSES having looked at nothing.                       *)\n(*                                                                         *)\n(* Add the values your claim is about, including ones this policy never    *)\n(* mentions.                                                               *)\n(***************************************************************************)\naccountValues == {Num(1), Num(2)}\namountValues == {Num(499), Num(500), Num(2500), Num(2501)}\ncharge_idValues == {Num(1), Num(2)}\nsystemNowTimeValues == {Num(32399999), Num(32400000), Num(61200000), Num(61200001)}\n\nRequests == {[account |-> account, amount |-> amount, charge_id |-> charge_id, systemNowTime |-> systemNowTime] : account \\in accountValues, amount \\in amountValues, charge_id \\in charge_idValues, systemNowTime \\in systemNowTimeValues}\n\n\\* One request, chosen nondeterministically and held, so a violation's counterexample NAMES the\n\\* request that breaks the claim rather than merely reporting that one exists.\nVARIABLE req\nInit == req \\in Requests\nNext == UNCHANGED req\nSpec == Init /\\ [][Nex
> ```
> 
> The intention to state formally:
> 
> A refund over $500 requires a supervisor approval for that charge within the previous 30 minutes.

| | |
|---|---|
| model | gemini-3.7-flash |
| tokens | 195,221 |
| seconds | 97.8 |

**Tool call 1** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec\n",
  "expression": "Policies",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
ld |-> "",
                             cmp |-> "",
                             value |-> [k |-> "s", v |-> ""],
                             other |-> "",
                             pattern |-> <<>>,
                             net |-> <<>>,
                             prefix |-> 0 ],
                       leftNeg |-> FALSE,
                       keys |-> <<>> ] ] ],
         [ effect |-> "permit",
           actions |-> {"request_approval"},
           cond |->
               [ op |-> "true",
                 args |-> <<>>,
                 term |->
                     [ op |-> "formerly",
                       window |-> 0,
                       atom |->
                           [ op |-> "pred",
                             args |-> <<>>,
                             pred |-> [action |-> "", kind |-> "", binds |-> <<>>],
                             var |-> "",
                             field |-> "",
                             cmp |-> "",
                             value |-> [k |-> "s", v |-> ""],
                             other |-> "",
                             pattern |-> <<>>,
                             net |-> <<>>,
                             prefix |-> 0 ],
                       left |->
                           [ op |-> "pred",
                             args |-> <<>>,
                             pred |-> [action |-> "", kind |-> "", binds |-> <<>>],
                             var |-> "",
                             field |-> "",
```

</details>

**Tool call 2** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec",
  "expression": "Policies[3]",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
-> "",
                                            field |-> "systemNowTime",
                                            cmp |-> ">=",
                                            value |-> [k |-> "n", v |-> 32400000],
                                            other |-> "",
                                            pattern |-> <<>>,
                                            net |-> <<>>,
                                            prefix |-> 0 ],
                                      leftNeg |-> FALSE,
                                      keys |-> <<"principal">> ] ],
                              [ op |-> "term",
                                args |-> <<>>,
                                term |->
                                    [ op |-> "at",
                                      window |-> 0,
                                      atom |->
                                          [ op |-> "cmp",
                                            args |-> <<>>,
                                            pred |->
                                                [ action |-> "",
                                                  kind |-> "",
                                                  binds |-> <<>> ],
                                            var |-> "",
                                            field |-> "systemNowTime",
                                            cmp |-> "<=",
                                            value |-> [k |-> "n", v |-> 61200000],
```

</details>

**Tool call 3** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec",
  "expression": "<<Policies[6], Policies[7]>>",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
 cmp |-> ">",
                 value |-> 3,
                 agg |->
                     [ kind |-> "count",
                       cond |->
                           [ op |-> "term",
                             args |-> <<>>,
                             term |->
                                 [ op |-> "formerly",
                                   window |-> 3600,
                                   atom |->
                                       [ op |-> "and",
                                         args |->
                                             << [ op |-> "pred",
                                                  args |-> <<>>,
                                                  pred |->
                                                      [ action |-> "issue_refund",
                                                        kind |-> "request",
                                                        binds |->
                                                            << [ kind |-> "ctx",
                                                                 field |-> "account",
                                                                 value |->
                                                                     [ k |-> "s",
                                                                       v |-> "" ],
                                                                 side |-> "input",
                                                                 name |->
```

</details>

**Tool call 4** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec",
  "expression": "Policies[7]",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
    prefix |-> 0 ],
                             leftNeg |-> FALSE,
                             keys |-> <<"principal">> ] ],
                     [ op |-> "not",
                       args |->
                           << [ op |-> "term",
                                args |-> <<>>,
                                term |->
                                    [ op |-> "formerly",
                                      window |-> 1800,
                                      atom |->
                                          [ op |-> "pred",
                                            args |-> <<>>,
                                            pred |->
                                                [ action |-> "request_approval",
                                                  kind |-> "response",
                                                  binds |->
                                                      << [ kind |-> "ctx",
                                                           field |-> "charge_id",
                                                           value |->
                                                               [k |-> "s", v |-> ""],
                                                           side |-> "input",
                                                           name |-> "charge_id" ],
                                                         [ kind |-> "lit",
                                                           field |-> "approved",
```

</details>

**Tool call 5** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec",
  "expression": "Policies[3].cond",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
                                   field |-> "systemNowTime",
                                      cmp |-> ">=",
                                      value |-> [k |-> "n", v |-> 32400000],
                                      other |-> "",
                                      pattern |-> <<>>,
                                      net |-> <<>>,
                                      prefix |-> 0 ],
                                leftNeg |-> FALSE,
                                keys |-> <<"principal">> ] ],
                        [ op |-> "term",
                          args |-> <<>>,
                          term |->
                              [ op |-> "at",
                                window |-> 0,
                                atom |->
                                    [ op |-> "cmp",
                                      args |-> <<>>,
                                      pred |->
                                          [ action |-> "",
                                            kind |-> "",
                                            binds |-> <<>> ],
                                      var |-> "",
                                      field |-> "systemNowTime",
                                      cmp |-> "<=",
                                      value |-> [k |-> "n", v |-> 61200000],
                                      other |-> "",
                                      pattern |-> <<>>,
                                      net |-> <<>>,
```

</details>

**Tool call 6** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec",
  "expression": "LET app == Ev(\"request_approval\", \"response\", [charge_id |-> Num(1), systemNowTime |-> Num(35000000)], [approved |-> Bool(TRUE), verified |-> Bool(TRUE)], 100)\n    ref == Ev(\"issue_refund\", \"request\", [account |-> Num(1), amount |-> Num(2500), charge_id |-> Num(1), systemNowTime |-> Num(35000000)], NoFields, 160)\nIN D!Decide(<<app, ref>>, Policies, 2, AllValues)",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
LET app == Ev("request_approval", "response", [charge_id |-> Num(1), systemNowTime |-> Num(35000000)], [approved |-> Bool(TRUE), verified |-> Bool(TRUE)], 100)
    ref == Ev("issue_refund", "request", [account |-> Num(1), amount |-> Num(2500), charge_id |-> Num(1), systemNowTime |-> Num(35000000)], NoFields, 160)
IN D!Decide(<<app, ref>>, Policies, 2, AllValues)

      TRUE
```

</details>

**Tool call 7** — `evaluate`

```json
{
  "config": "SPECIFICATION Spec",
  "expression": "LET app(cid, appr) == Ev(\"request_approval\", \"response\", [charge_id |-> Num(cid), systemNowTime |-> Num(35000000)], [approved |-> Bool(appr), verified |-> Bool(TRUE)], 100)\n    ref(amt, cid, t) == Ev(\"issue_refund\", \"request\", [account |-> Num(1), amount |-> Num(amt), charge_id |-> Num(cid), systemNowTime |-> Num(35000000)], NoFields, t)\nIN <<\n  D!Decide(<<app(1, TRUE), ref(2500, 1, 100 + 1800)>>, Policies, 2, AllValues), \\* 1800s gap: TRUE\n  D!Decide(<<app(1, TRUE), ref(2500, 1, 100 + 1801)>>, Policies, 2, AllValues), \\* 1801s gap: FALSE\n  D!Decide(<<app(2, TRUE), ref(2500, 1, 100 + 60)>>, Policies, 2, AllValues),   \\* mismatched charge: FALSE\n  D!Decide(<<app(1, FALSE), ref(2500, 1, 100 + 60)>>, Policies, 2, AllValues),  \\* not approved: FALSE\n  D!Decide(<<ref(2500, 1, 100)>>, Policies, 1, AllValues),                       \\* no approval: FALSE\n  D!Decide(<<ref(500, 1, 100)>>, Policies, 1, AllValues),                        \\* amount = 500 without approval: TRUE\n  D!Decide(<<ref(499, 1, 100)>>, Policies, 1, AllValues)                         \\* amount = 499 without approval: TRUE\n>>",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\nVARIABLE dummy\nInit == dummy = 0\nNext == UNCHANGED dummy\nSpec == Init /\\ [][Next]_dummy\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
LET app(cid, appr) == Ev("request_approval", "response", [charge_id |-> Num(cid), systemNowTime |-> Num(35000000)], [approved |-> Bool(appr), verified |-> Bool(TRUE)], 100)
    ref(amt, cid, t) == Ev("issue_refund", "request", [account |-> Num(1), amount |-> Num(amt), charge_id |-> Num(cid), systemNowTime |-> Num(35000000)], NoFields, t)
IN <<
  D!Decide(<<app(1, TRUE), ref(2500, 1, 100 + 1800)>>, Policies, 2, AllValues), \* 1800s gap: TRUE
  D!Decide(<<app(1, TRUE), ref(2500, 1, 100 + 1801)>>, Policies, 2, AllValues), \* 1801s gap: FALSE
  D!Decide(<<app(2, TRUE), ref(2500, 1, 100 + 60)>>, Policies, 2, AllValues),   \* mismatched charge: FALSE
  D!Decide(<<app(1, FALSE), ref(2500, 1, 100 + 60)>>, Policies, 2, AllValues),  \* not approved: FALSE
  D!Decide(<<ref(2500, 1, 100)>>, Policies, 1, AllValues),                       \* no approval: FALSE
  D!Decide(<<ref(500, 1, 100)>>, Policies, 1, AllValues),                        \* amount = 500 without approval: TRUE
  D!Decide(<<ref(499, 1, 100)>>, Policies, 1, AllValues)                         \* amount = 499 without approval: TRUE
>>

      <<TRUE, FALSE, FALSE, FALSE, FALSE, TRUE, TRUE>>
```

</details>

**Tool call 8** — `check_module`

```json
{
  "config": "SPECIFICATION Spec\nINVARIANT Over500RequiresApproval\nINVARIANT ApprovedRefundIsAllowed\nINVARIANT SmallRefundWithoutApprovalIsAllowed\n",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\n\nAmounts == {499, 500, 2500, 2501}\nBooleans == {TRUE, FALSE}\nChargeIds == {1, 2}\nGaps == {60, 1800, 1801}\n\nVARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap\n\nInit ==\n    /\\ amount \\in Amounts\n    /\\ has_approval \\in Booleans\n    /\\ approved \\in Booleans\n    /\\ approval_charge \\in ChargeIds\n    /\\ refund_charge \\in ChargeIds\n    /\\ gap \\in Gaps\n\nNext == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nSpec == Init /\\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nApprovalEv ==\n    Ev(\"request_approval\", \"response\",\n       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],\n       [approved |-> Bool(approved), verified |-> Bool(TRUE)],\n       100)\n\nRefundEv ==\n    Ev(\"issue_refund\", DecisionKind,\n       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],\n       NoFields,\n       IF has_approval THEN 100 + gap ELSE 100)\n\nSession ==\n    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>\n\nDecisionIndex ==\n    IF has_approval THEN 2 ELSE 1\n\nRefundAllowed ==\n    D!Decide(Session, Policies, DecisionIndex, AllValues)\n\nHasValidApproval ==\n    /\\ has_approval\n    /\\ approved\n    /\\ approval_charge = refund_charge\n    /\\ gap <= 1800\n\nOver500RequiresApproval ==\n    (amount > 500 /\\ ~HasValidApproval) => ~RefundAllowed\n\nApprovedRefundIsAllowed ==\n    (amount = 2500 /\\ has_approval /\\ approved /\\ approval_charge = 1 /\\ refund_charge = 1 /\\ gap = 60) => RefundAllowed\n\nSmallRefundWithoutApprovalIsAllowed ==\n    (amount = 500 /\\ ~has_approval /\\ refund_charge = 1) => RefundAllowed\n\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
Compiles, evaluates, and holds on this policy. Either answer is acceptable -- a property that fails has already shown it discriminates. Do NOT weaken the claim to make it hold.
```

</details>

**Tool call 9** — `what_it_forbids`

```json
{
  "config": "SPECIFICATION Spec\nINVARIANT Over500RequiresApproval\nINVARIANT ApprovedRefundIsAllowed\nINVARIANT SmallRefundWithoutApprovalIsAllowed\n",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\n\nAmounts == {499, 500, 2500, 2501}\nBooleans == {TRUE, FALSE}\nChargeIds == {1, 2}\nGaps == {60, 1800, 1801}\n\nVARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap\n\nInit ==\n    /\\ amount \\in Amounts\n    /\\ has_approval \\in Booleans\n    /\\ approved \\in Booleans\n    /\\ approval_charge \\in ChargeIds\n    /\\ refund_charge \\in ChargeIds\n    /\\ gap \\in Gaps\n\nNext == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nSpec == Init /\\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nApprovalEv ==\n    Ev(\"request_approval\", \"response\",\n       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],\n       [approved |-> Bool(approved), verified |-> Bool(TRUE)],\n       100)\n\nRefundEv ==\n    Ev(\"issue_refund\", DecisionKind,\n       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],\n       NoFields,\n       IF has_approval THEN 100 + gap ELSE 100)\n\nSession ==\n    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>\n\nDecisionIndex ==\n    IF has_approval THEN 2 ELSE 1\n\nRefundAllowed ==\n    D!Decide(Session, Policies, DecisionIndex, AllValues)\n\nHasValidApproval ==\n    /\\ has_approval\n    /\\ approved\n    /\\ approval_charge = refund_charge\n    /\\ gap <= 1800\n\nOver500RequiresApproval ==\n    (amount > 500 /\\ ~HasValidApproval) => ~RefundAllowed\n\nApprovedRefundIsAllowed ==\n    (amount = 2500 /\\ has_approval /\\ approved /\\ approval_charge = 1 /\\ refund_charge = 1 /\\ gap = 60) => RefundAllowed\n\nSmallRefundWithoutApprovalIsAllowed ==\n    (amount = 500 /\\ ~has_approval /\\ refund_charge = 1) => RefundAllowed\n\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
SupervisorApproval

  3 claims will be checked, over 192 states:

  Over500RequiresApproval
      says:     whenever amount is greater than 500 and HasValidApproval does not hold,
                then the policy REFUSES it (RefundAllowed)
      forbids:  amount is greater than 500 and HasValidApproval does not hold,
                and yet the policy GRANTS it (RefundAllowed)
      applies:  unknown -- `amount > 500 /\ ~HasValidApproval` could not be worked out
                here for 96 of the 192 states

  ApprovedRefundIsAllowed
      says:     whenever amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 2500, has_approval = TRUE, approved = TRUE, approval_charge =
                    1, refund_charge = 1, gap = 60

  SmallRefundWithoutApprovalIsAllowed
      says:     whenever amount is 500 and has_approval does not hold and refund_charge
                is 1,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 500 and has_approval does not hold and refund_charge is 1,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 12 of the 192 states:
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 60
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 1800
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 1801
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 2, refund_charge = 1, gap = 60
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 2, refund_charge = 1, gap = 1800
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 2, refund_charge = 1, gap = 1801
                  and 6 more

  !!        defined here but NOT named in the .cfg, so not checked: HasValidApproval. A
            claim nobody listed is a claim nobody checked

  Read the `forbids` lines before the run, not after it. Each one is the only
  thing its claim can catch; if none of them describes something you would
  object to, the check will pass without having tested what you meant.
```

</details>

**Tool call 10** — `what_it_forbids`

```json
{
  "config": "SPECIFICATION Spec\nINVARIANT Over500RequiresApproval\nINVARIANT ApprovedRefundIsAllowed\nINVARIANT SmallRefundWithoutApprovalIsAllowed\n",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\n\nAmounts == {499, 500, 2500, 2501}\nBooleans == {TRUE, FALSE}\nChargeIds == {1, 2}\nGaps == {60, 1800, 1801}\n\nVARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap\n\nInit ==\n    /\\ amount \\in Amounts\n    /\\ has_approval \\in Booleans\n    /\\ approved \\in Booleans\n    /\\ approval_charge \\in ChargeIds\n    /\\ refund_charge \\in ChargeIds\n    /\\ gap \\in Gaps\n\nNext == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nSpec == Init /\\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nApprovalEv ==\n    Ev(\"request_approval\", \"response\",\n       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],\n       [approved |-> Bool(approved), verified |-> Bool(TRUE)],\n       100)\n\nRefundEv ==\n    Ev(\"issue_refund\", DecisionKind,\n       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],\n       NoFields,\n       IF has_approval THEN 100 + gap ELSE 100)\n\nSession ==\n    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>\n\nDecisionIndex ==\n    IF has_approval THEN 2 ELSE 1\n\nRefundAllowed ==\n    D!Decide(Session, Policies, DecisionIndex, AllValues)\n\nisValidApproval ==\n    /\\ has_approval\n    /\\ approved\n    /\\ approval_charge = refund_charge\n    /\\ gap <= 1800\n\nOver500RequiresApproval ==\n    (amount > 500 /\\ ~isValidApproval) => ~RefundAllowed\n\nApprovedRefundIsAllowed ==\n    (amount = 2500 /\\ has_approval /\\ approved /\\ approval_charge = 1 /\\ refund_charge = 1 /\\ gap = 60) => RefundAllowed\n\nSmallRefundWithoutApprovalIsAllowed ==\n    (amount = 500 /\\ ~has_approval /\\ refund_charge = 1 /\\ gap = 60 /\\ approval_charge = 1 /\\ ~approved) => RefundAllowed\n\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
SupervisorApproval

  3 claims will be checked, over 192 states:

  Over500RequiresApproval
      says:     whenever amount is greater than 500 and isValidApproval does not hold,
                then the policy REFUSES it (RefundAllowed)
      forbids:  amount is greater than 500 and isValidApproval does not hold,
                and yet the policy GRANTS it (RefundAllowed)
      applies:  unknown -- `amount > 500 /\ ~isValidApproval` could not be worked out
                here for 96 of the 192 states

  ApprovedRefundIsAllowed
      says:     whenever amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 2500, has_approval = TRUE, approved = TRUE, approval_charge =
                    1, refund_charge = 1, gap = 60

  SmallRefundWithoutApprovalIsAllowed
      says:     whenever amount is 500 and has_approval does not hold and refund_charge
                is 1 and gap is 60 and approval_charge is 1 and approved does not hold,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 500 and has_approval does not hold and refund_charge is 1 and
                gap is 60 and approval_charge is 1 and approved does not hold,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 60

  !!        defined here but NOT named in the .cfg, so not checked: isValidApproval. A
            claim nobody listed is a claim nobody checked

  Read the `forbids` lines before the run, not after it. Each one is the only
  thing its claim can catch; if none of them describes something you would
  object to, the check will pass without having tested what you meant.
```

</details>

**Tool call 11** — `what_it_forbids`

```json
{
  "config": "SPECIFICATION Spec\nINVARIANT Over500RequiresApproval\nINVARIANT ApprovedRefundIsAllowed\nINVARIANT SmallRefundWithoutApprovalIsAllowed\n",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\n\nAmounts == {499, 500, 2500, 2501}\nBooleans == {TRUE, FALSE}\nChargeIds == {1, 2}\nGaps == {60, 1800, 1801}\n\nVARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap\n\nInit ==\n    /\\ amount \\in Amounts\n    /\\ has_approval \\in Booleans\n    /\\ approved \\in Booleans\n    /\\ approval_charge \\in ChargeIds\n    /\\ refund_charge \\in ChargeIds\n    /\\ gap \\in Gaps\n\nNext == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nSpec == Init /\\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nApprovalEv ==\n    Ev(\"request_approval\", \"response\",\n       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],\n       [approved |-> Bool(approved), verified |-> Bool(TRUE)],\n       100)\n\nRefundEv ==\n    Ev(\"issue_refund\", DecisionKind,\n       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],\n       NoFields,\n       IF has_approval THEN 100 + gap ELSE 100)\n\nSession ==\n    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>\n\nDecisionIndex ==\n    IF has_approval THEN 2 ELSE 1\n\nRefundAllowed ==\n    D!Decide(Session, Policies, DecisionIndex, AllValues)\n\nValidApproval(h, app, ac, rc, g) ==\n    /\\ h\n    /\\ app\n    /\\ ac = rc\n    /\\ g <= 1800\n\nOver500RequiresApproval ==\n    (amount > 500 /\\ ~ValidApproval(has_approval, approved, approval_charge, refund_charge, gap)) => ~RefundAllowed\n\nApprovedRefundIsAllowed ==\n    (amount = 2500 /\\ has_approval /\\ approved /\\ approval_charge = 1 /\\ refund_charge = 1 /\\ gap = 60) => RefundAllowed\n\nSmallRefundWithoutApprovalIsAllowed ==\n    (amount = 500 /\\ ~has_approval /\\ refund_charge = 1 /\\ gap = 60 /\\ approval_charge = 1 /\\ ~approved) => RefundAllowed\n\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
SupervisorApproval

  3 claims will be checked, over 192 states:

  Over500RequiresApproval
      says:     whenever amount is greater than 500 and ValidApproval(has_approval,
                approved, approval_charge, refund_charge, gap) does not hold,
                then the policy REFUSES it (RefundAllowed)
      forbids:  amount is greater than 500 and ValidApproval(has_approval, approved,
                approval_charge, refund_charge, gap) does not hold,
                and yet the policy GRANTS it (RefundAllowed)
      applies:  to 88 of the 192 states:
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 60
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 1800
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 1801
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 2, gap = 60
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 2, gap = 1800
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 2, gap = 1801
                  and 82 more

  ApprovedRefundIsAllowed
      says:     whenever amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 2500, has_approval = TRUE, approved = TRUE, approval_charge =
                    1, refund_charge = 1, gap = 60

  SmallRefundWithoutApprovalIsAllowed
      says:     whenever amount is 500 and has_approval does not hold and refund_charge
                is 1 and gap is 60 and approval_charge is 1 and approved does not hold,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 500 and has_approval does not hold and refund_charge is 1 and
                gap is 60 and approval_charge is 1 and approved does not hold,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 60

  Read the `forbids` lines before the run, not after it. Each one is the only
  thing its claim can catch; if none of them describes something you would
  object to, the check will pass without having tested what you meant.
```

</details>

**Tool call 12** — `check_module`

```json
{
  "config": "SPECIFICATION Spec\nINVARIANT Over500RequiresApproval\nINVARIANT ApprovedRefundIsAllowed\nINVARIANT SmallRefundWithoutApprovalIsAllowed\n",
  "module": "---------------------------- MODULE SupervisorApproval ----------------------------\nEXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n\nD == INSTANCE DogwoodSemantics WITH Cases <- << >>\n\nAmounts == {499, 500, 2500, 2501}\nBooleans == {TRUE, FALSE}\nChargeIds == {1, 2}\nGaps == {60, 1800, 1801}\n\nVARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap\n\nInit ==\n    /\\ amount \\in Amounts\n    /\\ has_approval \\in Booleans\n    /\\ approved \\in Booleans\n    /\\ approval_charge \\in ChargeIds\n    /\\ refund_charge \\in ChargeIds\n    /\\ gap \\in Gaps\n\nNext == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nSpec == Init /\\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>\n\nApprovalEv ==\n    Ev(\"request_approval\", \"response\",\n       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],\n       [approved |-> Bool(approved), verified |-> Bool(TRUE)],\n       100)\n\nRefundEv ==\n    Ev(\"issue_refund\", DecisionKind,\n       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],\n       NoFields,\n       IF has_approval THEN 100 + gap ELSE 100)\n\nSession ==\n    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>\n\nDecisionIndex ==\n    IF has_approval THEN 2 ELSE 1\n\nRefundAllowed ==\n    D!Decide(Session, Policies, DecisionIndex, AllValues)\n\nValidApproval(h, app, ac, rc, g) ==\n    /\\ h\n    /\\ app\n    /\\ ac = rc\n    /\\ g <= 1800\n\nOver500RequiresApproval ==\n    (amount > 500 /\\ ~ValidApproval(has_approval, approved, approval_charge, refund_charge, gap)) => ~RefundAllowed\n\nApprovedRefundIsAllowed ==\n    (amount = 2500 /\\ has_approval /\\ approved /\\ approval_charge = 1 /\\ refund_charge = 1 /\\ gap = 60) => RefundAllowed\n\nSmallRefundWithoutApprovalIsAllowed ==\n    (amount = 500 /\\ ~has_approval /\\ refund_charge = 1 /\\ gap = 60 /\\ approval_charge = 1 /\\ ~approved) => RefundAllowed\n\n============================================================================="
}
```

<details><summary>tool result (success)</summary>

```
Compiles, evaluates, and holds on this policy. Either answer is acceptable -- a property that fails has already shown it discriminates. Do NOT weaken the claim to make it hold.
```

</details>

===MODULE===
---------------------------- MODULE SupervisorApproval ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Amounts == {499, 500, 2500, 2501}
Booleans == {TRUE, FALSE}
ChargeIds == {1, 2}
Gaps == {60, 1800, 1801}

VARIABLES amount, has_approval, approved, approval_charge, refund_charge, gap

Init ==
    /\ amount \in Amounts
    /\ has_approval \in Booleans
    /\ approved \in Booleans
    /\ approval_charge \in ChargeIds
    /\ refund_charge \in ChargeIds
    /\ gap \in Gaps

Next == UNCHANGED << amount, has_approval, approved, approval_charge, refund_charge, gap >>

Spec == Init /\ [][Next]_<< amount, has_approval, approved, approval_charge, refund_charge, gap >>

ApprovalEv ==
    Ev("request_approval", "response",
       [charge_id |-> Num(approval_charge), systemNowTime |-> Num(35000000)],
       [approved |-> Bool(approved), verified |-> Bool(TRUE)],
       100)

RefundEv ==
    Ev("issue_refund", DecisionKind,
       [account |-> Num(1), amount |-> Num(amount), charge_id |-> Num(refund_charge), systemNowTime |-> Num(35000000)],
       NoFields,
       IF has_approval THEN 100 + gap ELSE 100)

Session ==
    IF has_approval THEN << ApprovalEv, RefundEv >> ELSE << RefundEv >>

DecisionIndex ==
    IF has_approval THEN 2 ELSE 1

RefundAllowed ==
    D!Decide(Session, Policies, DecisionIndex, AllValues)

ValidApproval(h, app, ac, rc, g) ==
    /\ h
    /\ app
    /\ ac = rc
    /\ g <= 1800

Over500RequiresApproval ==
    (amount > 500 /\ ~ValidApproval(has_approval, approved, approval_charge, refund_charge, gap)) => ~RefundAllowed

ApprovedRefundIsAllowed ==
    (amount = 2500 /\ has_approval /\ approved /\ approval_charge = 1 /\ refund_charge = 1 /\ gap = 60) => RefundAllowed

SmallRefundWithoutApprovalIsAllowed ==
    (amount = 500 /\ ~has_approval /\ refund_charge = 1 /\ gap = 60 /\ approval_charge = 1 /\ ~approved) => RefundAllowed

=============================================================================
===CONFIG===
SPECIFICATION Spec
INVARIANT Over500RequiresApproval
INVARIANT ApprovedRefundIsAllowed
INVARIANT SmallRefundWithoutApprovalIsAllowed

## the review

**Asked:**

> THE REQUIREMENT:
> 
> A refund over $500 requires a supervisor approval for that charge within the previous 30 minutes.
> 
> THE READING OF THE FORMAL CLAIM WRITTEN TO CAPTURE IT:
> 
> SupervisorApproval
> 
>   3 claims will be checked, over 192 states:
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>         refund_charge = 1, gap = 60
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>         refund_charge = 1, gap = 1800
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>         refund_charge = 1, gap = 1801
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>         refund_charge = 2, gap = 60
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>         refund_charge = 2, gap = 1800
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>         refund_charge = 2, gap = 1801
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 2,
>         refund_charge = 1, gap = 60
>       amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 2,
>         refund_charge = 1, gap = 1800
>       and 184 more
> 
>   Over500RequiresApproval
>       says:     whenever amount is greater than 500 and ValidApproval(has_approval,
>                 approved, approval_charge, refund_charge, gap) does not hold,
>                 then the policy REFUSES it (RefundAllowed)
>       forbids:  amount is greater than 500 and ValidApproval(has_approval, approved,
>                 approval_charge, refund_charge, gap) does not hold,
>                 and yet the policy GRANTS it (RefundAllowed)
>       applies:  to 88 of the 192 states:
>                   amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 1, gap = 60
>                   amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 1, gap = 1800
>                   amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 1, gap = 1801
>                   amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 2, gap = 60
>                   amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 2, gap = 1800
>                   amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 2, gap = 1801
>                   and 82 more
> 
>   ApprovedRefundIsAllowed
>       says:     whenever amount is 2500 and has_approval holds and approved holds and
>                 approval_charge is 1 and refund_charge is 1 and gap is 60,
>                 then the policy GRANTS it (RefundAllowed)
>       forbids:  amount is 2500 and has_approval holds and approved holds and
>                 approval_charge is 1 and refund_charge is 1 and gap is 60,
>                 and yet the policy REFUSES it (RefundAllowed)
>       applies:  to 1 of the 192 states:
>                   amount = 2500, has_approval = TRUE, approved = TRUE, approval_charge =
>                     1, refund_charge = 1, gap = 60
> 
>   SmallRefundWithoutApprovalIsAllowed
>       says:     whenever amount is 500 and has_approval does not hold and refund_charge
>                 is 1 and gap is 60 and approval_charge is 1 and approved does not hold,
>                 then the policy GRANTS it (RefundAllowed)
>       forbids:  amount is 500 and has_approval does not hold and refund_charge is 1 and
>                 gap is 60 and approval_charge is 1 and approved does not hold,
>                 and yet the policy REFUSES it (RefundAllowed)
>       applies:  to 1 of the 192 states:
>                   amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
>                     = 1, refund_charge = 1, gap = 60
> 
>   Read the `forbids` lines before the run, not after it. Each one is the only
>   thing its claim can catch; if none of them describes something you would
>   object to, the check will pass without having tested what you meant.

| | |
|---|---|
| model | gemini-3.7-flash |
| tokens | 1,733 |
| seconds | 4.2 |

VERDICT: MATCH

The formal reading accurately captures the requirement that refunds exceeding $500 require a valid supervisor approval for the specific charge within the 30-minute window (checked up to 1800 seconds). It correctly verifies that refunds over $500 lacking valid approval are refused, while also testing standard valid approval and below-threshold cases.

## the report

**Asked:**

> Policy set: agent-policy.dw
> Property module: SupervisorApproval.tla
> 
> The property module HOLDS: every claim in it holds.
> 
> WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the states it ranges over its condition applies to:
> 
> SupervisorApproval
> 
>   3 claims will be checked, over 192 states:
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>     refund_charge = 1, gap = 60
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>     refund_charge = 1, gap = 1800
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>     refund_charge = 1, gap = 1801
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>     refund_charge = 2, gap = 60
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>     refund_charge = 2, gap = 1800
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
>     refund_charge = 2, gap = 1801
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 2,
>     refund_charge = 1, gap = 60
>   amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 2,
>     refund_charge = 1, gap = 1800
>   and 184 more
> 
>   Over500RequiresApproval
>   says:     whenever amount is greater than 500 and ValidApproval(has_approval,
>             approved, approval_charge, refund_charge, gap) does not hold,
>             then the policy REFUSES it (RefundAllowed)
>   forbids:  amount is greater than 500 and ValidApproval(has_approval, approved,
>             approval_charge, refund_charge, gap) does not hold,
>             and yet the policy GRANTS it (RefundAllowed)
>   applies:  to 88 of the 192 states:
>               amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 1, gap = 60
>               amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 1, gap = 1800
>               amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 1, gap = 1801
>               amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 2, gap = 60
>               amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 2, gap = 1800
>               amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 2, gap = 1801
>               and 82 more
> 
>   ApprovedRefundIsAllowed
>   says:     whenever amount is 2500 and has_approval holds and approved holds and
>             approval_charge is 1 and refund_charge is 1 and gap is 60,
>             then the policy GRANTS it (RefundAllowed)
>   forbids:  amount is 2500 and has_approval holds and approved holds and
>             approval_charge is 1 and refund_charge is 1 and gap is 60,
>             and yet the policy REFUSES it (RefundAllowed)
>   applies:  to 1 of the 192 states:
>               amount = 2500, has_approval = TRUE, approved = TRUE, approval_charge =
>                 1, refund_charge = 1, gap = 60
> 
>   SmallRefundWithoutApprovalIsAllowed
>   says:     whenever amount is 500 and has_approval does not hold and refund_charge
>             is 1 and gap is 60 and approval_charge is 1 and approved does not hold,
>             then the policy GRANTS it (RefundAllowed)
>   forbids:  amount is 500 and has_approval does not hold and refund_charge is 1 and
>             gap is 60 and approval_charge is 1 and approved does not hold,
>             and yet the policy REFUSES it (RefundAllowed)
>   applies:  to 1 of the 192 states:
>               amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
>                 = 1, refund_charge = 1, gap = 60
> 
>   Read the `forbids` lines before the run, not after it. Each one is the only
>   thing its claim can catch; if none of them describes something you would
>   object to, the check will pass without having tested what you meant.
> 
> This says nothing about requests the property module does not name.
> 
> The derived questions were NOT attempted: this policy is outside the subset they can range over.
>   REFUSED: agent-policy.dw is outside the modelled subset
>   policy reads 6 input/output fields; the request space is the product of their domains, so this would explode (limit 4, raise with --max-fields)
> That is a limit of those questions, not a verdict about the policy.

| | |
|---|---|
| model | gemini-3.7-flash |
| tokens | 3,281 |
| seconds | 11.2 |

### Verification Summary

All 3 claims in `SupervisorApproval.tla` **held** across the **192 states** explored by the model checker. No counterexamples were found within this tested subset.

However, two of the three claims test only single, specific request configurations rather than broader conditions. Furthermore, derived general questions were not evaluated.

---

### What Was Checked and What Held

The checker evaluated combinations formed from discrete values across 6 variables:
* **`amount`**: sampled values including `499`, `500`, and `2500`
* **`has_approval`**: `TRUE`, `FALSE`
* **`approved`**: `TRUE`, `FALSE`
* **`approval_charge`**: `1`, `2`
* **`refund_charge`**: `1`, `2`
* **`gap`**: `60`, `1800`, `1801`

Total state space explored: **192 states**.

---

### Claim-by-Claim Results

#### 1. `Over500RequiresApproval`
* **Verdict:** Held.
* **Scope:** Applied to **88 of the 192 states** (specifically where `amount = 2500` and `ValidApproval(...)` is false).
* **Behavior:** In all 88 applicable states where the amount exceeded 500 without valid approval, the policy refused the refund (`RefundAllowed` was false).

#### 2. `ApprovedRefundIsAllowed`
* **Verdict:** Held.
* **Scope:** Applied to **1 of the 192 states**.
* **Finding on Property Design:** This property only tests a single point:
  * `amount = 2500`
  * `has_approval = TRUE`
  * `approved = TRUE`
  * `approval_charge = 1`
  * `refund_charge = 1`
  * `gap = 60`
  
  The property did not test whether approvals are granted for other amounts over 500, other valid charge identifiers, or other valid gap durations (e.g., `gap = 1800`).

#### 3. `SmallRefundWithoutApprovalIsAllowed`
* **Verdict:** Held.
* **Scope:** Applied to **1 of the 192 states**.
* **Finding on Property Design:** This property also tests only a single point:
  * `amount = 500`
  * `has_approval = FALSE`
  * `approved = FALSE`
  * `approval_charge = 1`
  * `refund_charge = 1`
  * `gap = 60`
  
  It did not test whether unapproved refunds are permitted for other small amounts (such as `amount = 499`) or across other charge IDs and gap values.

---

### What Was Not Checked

1. **Unchecked Request Values:** Any inputs outside the sampled values—including amounts other than `499`, `500`, and `2500`, gaps other than `60`, `1800`, and `1801`, or charge IDs other than `1` and `2`—were not evaluated.
2. **Derived General Questions:** Automated derived property checks were skipped because `agent-policy.dw` evaluates 6 input/output fields, exceeding the default 4-field limit.
