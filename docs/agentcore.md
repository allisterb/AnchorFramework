# AgentCore's layer over Dogwood

What Amazon Bedrock AgentCore adds to Dogwood, rule by rule, and what Anchor does about each.
Step 1 of the plan in `docs/agent/HANDOFF.md`. **No code changed for this document.** It defines
the target for steps 2–5.

Written 2026-10-02 from four pages of the AgentCore Developer Guide, saved under `reference/docs/`
and recorded in the reference ledger:

| short name | file | sections cited |
|---|---|---|
| **Temporal** | `policy-temporal.md` | Policy sessions · Session invalidation · Considerations · Quotas · Security considerations |
| **Authoring** | `policy-temporal-authoring.md` | Create · Event schema · Use cases (14 examples, `FundsTarget`) |
| **Examples** | `example-policies-temporal.md` | Before you use these examples · 14 examples (`InsuranceAPI`) · What changes when you edit |
| **Reference** | `example-policies-reference.md` | Action names · MCP tools · Principals · Parameter types |

## The short version

- **AgentCore publishes its event schema, and it is written in Dogwood's own `.dwschema` syntax**
  (Authoring, *Event schema*). Most of the questions the plan left open are answered by reading
  it. Step 3's `agentcore.dwschema` is a transcription of it, not a reconstruction.
- **History is partitioned by session and nothing else.** `pin sessionId: String = context.sessionId`
  appears on all three event kinds. That makes it a universal symmetric pin, so Dogwood's key-local
  semantics apply, keyed on the session. `eventPrincipal` carries no pin. Within a session, events
  from every principal are visible.
- **`eventPrincipal` / `eventResource` are Dogwood's renamed scope fields**, typed
  `principalType(A)` / `resourceType(A)`, exactly as in Dogwood's corpus case
  `1110_custom_event_schema_renamed_reserved`. Neither is pinned.
- **The mandatory `eventResource: resource` is what makes a one-gateway model sound**, for every
  operator AgentCore documents. Positive-left `since` and `previous` are the exceptions; see below.
- **Two findings are worth carrying into step 4 and the email.** The response-recording delay lets
  a pipelining client spend a one-time approval twice. And in the mutual-exclusion pattern, a
  *denied* attempt still locks out the other action. Neither appears in AWS's decision tables.

## AgentCore's event schema

The schema as the guide prints it is a Dogwood event schema (Authoring, *Event schema*). Its
decision kind:

```
decision event <A>::request {
    ...inputs(A),
    eventPrincipal: principalType(A),
    eventResource:  resourceType(A),
    requestId:      String,
    pin sessionId:  String = context.sessionId,
}
```

`<A>::response` adds `...outputs(A)` and is history-only. `<A>::error` has the same fields as
`request` and is history-only. There is no `max_window` directive, so Dogwood's default of 24h
applies, which matches the quota (Temporal, *Quotas*).

**It is Dogwood's shipped `session-pinned` preset with two fields renamed** (`callerPrincipal` →
`eventPrincipal`, `callerResource` → `eventResource`), and identical otherwise. Anchor already reads
that preset and has it engine-validated (`dogwood_replay.py`). So the AgentCore reading is not a new
semantics: it is a known one, under different field names. The transcription is
`tests/policies/agentcore/agentcore.dwschema`.

**This is AWS's documentation of the schema, not the service's file.** Two things corroborate it:

- The rejection message in Examples (*Require a prior approval*, Important box) lists the declared
  fields of a response with no output schema as `eventPrincipal, eventResource, input.orderId,
  requestId, sessionId`. That is exactly what this schema derives for such a tool.
- The message has the same shape as `dogwood validate`'s, and `dogwood validate` produced it here
  under the default schema (HANDOFF, *What is already established*). So AgentCore's validator is
  very likely Dogwood's, run under this schema.

Step 3 checks it directly: `dogwood validate` should accept the guide's examples under the
transcribed schema, and `dogwood replay` should reproduce the decision tables.

**What it means for Anchor's code.** `src/translator/schema.py` knows the scope fields by **name**:
`SCOPE_PINS = {"callerPrincipal": …, "callerResource": …}`, with every other name refused through
`CONVENTIONAL_FIELDS`. Dogwood knows them by **type**: a field typed `principalType(A)` is the
principal, whatever it is called (Dogwood guide `03-event-schema.md`, *How request references
resolve*). Step 4 should recognise scope fields by their type selector. `eventPrincipal`,
`eventResource`, `actor` and `callerPrincipal` then become one case, not a list of names.

## The rules, classified

**Class** says what Anchor should do with each rule:

- **model**: the rule changes which decisions are reachable, so the model must carry it.
- **lint**: AgentCore would refuse to create the policy. Anchor should say so as a verdict of its
  own, distinct from REFUSED (which means the construct is outside Anchor's subset).
- **assumption**: not modelled. Stated, so a verdict is read with it in mind.
- **guarantee**: something AgentCore enforces that Anchor's model already takes for granted.
- **out of scope**: no bearing on a decision Anchor can reason about.

### The event model

| rule | source | class | Anchor today |
|---|---|---|---|
| Event kinds are `request` (decision), `response` and `error` (history-only) | Authoring, *Event schema* | model | modelled; same as Dogwood's default |
| Scope fields are named `eventPrincipal` / `eventResource` | Authoring, *Event schema* | model | **refused** (`CONVENTIONAL_FIELDS`) |
| History is per session; universal symmetric pin on `sessionId` | Authoring, *Event schema*; Temporal, *Policy sessions* | model | modelled as Dogwood's `session-pinned` preset, but only under Dogwood's field names |
| `eventPrincipal` is **not** pinned: one session can hold several principals' events | Authoring, *Event schema*; Examples, *Threshold* note ("correlate on `eventPrincipal`") | model | not reachable: see *Principals within a session* below |
| A `request` event is recorded for every request, including denied ones | Examples, *Require a prerequisite action* ("only has to have been **attempted**"); Dogwood semantics | model | modelled |
| A `response` is recorded only if the request was permitted **and** the tool succeeded | Temporal, *A prior action must be permitted*; Examples, *Before you use* | model | modelled |
| An `error` is recorded on a denial **or** a tool failure | Authoring, *Event schema* | model | modelled |
| The current request's own `request` event is in the history it is judged against | Temporal, *Self-referential conditions* | model | modelled (Dogwood semantics) |
| `output.*` exists on a `response` only if the tool declares an output schema | Examples, *Require a prior approval*, Important | **lint** | not checked. Needs the tool schemas as an input |

Authoring's wording, "recorded for each **authorized** request", reads as "each request submitted
for authorization". "Each permitted request" would contradict both Examples' "attempted" and the
mutual-exclusion example. That example only works if a request event is recorded before its own
decision.

### Policy shape

| rule | source | class | Anchor today |
|---|---|---|---|
| Every temporal predicate must contain `eventResource: resource` | Authoring, *Event schema* table; Examples, *Before you use* | **lint** + model | **refused** as a bind |
| Scope `resource == AgentCore::Gateway::"arn:…"` | every example | model | **refused** (scope naming an entity) |
| `principal is AgentCore::OAuthUser` (and `AgentCore::IamEntity`) | Examples, *Combine temporal, guardrail…*; Reference, *Principals* | model | refused |
| Action names: `Target___tool` (MCP) and `Target___METHOD:/path` (runtime, inference) | Reference, *Action names* | model | opaque strings. Step 2 confirms the parser accepts `:` and `/` |
| At most **3 temporal operators** per policy | Temporal, *Quotas*; Examples, *Two prerequisites* ("two of the three") | **lint** | not checked. How aggregates count is **open**, below |
| At most **20 temporal policies** per policy engine | Temporal, *Quotas* | **lint** | not checked |
| Window at most **24h** | Temporal, *Quotas* | lint | already enforced through `max_window` (default 24h) |
| Ordering in a temporal block needs integers on both sides | Examples, *Before you use*; Reference, *Numeric parameters* | **lint** | **refused** today. Should become the lint, since AgentCore rejects it at creation |
| `sum` needs an integer summand | same | **lint** | refused today, as above |
| Reading an optional input without a `has` guard fails creation (asynchronously: 202, then `CREATE_FAILED`) | Reference, *Numeric parameters*, last paragraphs | **lint** | not checked. Needs the tool schemas |
| JSON `number` is Cedar `decimal`, `integer` is `Long` | Reference, *Parameter types* | model | decimals modelled; the mapping needs the tool schemas |
| `when temporal {…} when {…} unless {…}` in one policy | Authoring, *Combining*; Examples, *Combine* | model | modelled |
| `BedrockGuardrails::SensitiveInformation(…)` | Authoring, *Combining*; Examples, *Combine* | out of scope | **refused**, as an information provider (`the-modelled-subset`) |
| `principal.hasTag(…)` / `getTag(…)` | Examples, *Combine*; Reference, *Principals* | out of scope | refused (entity attributes, deliberate) |
| Array members of inference and runtime request bodies | Reference, *Inference request bodies* | out of scope | array terms not modelled. AgentCore cannot reach them in a field path either |

Several lint rules need **the gateway's tool schemas**: which fields are optional, which are
integers, and which tools declare outputs. Anchor has no input for them today. Dogwood's
`dogwood schema mcp` builds a `.cedarschema` from an MCP `tools/list` manifest. That is the natural
input, and it would also give step 3's `dogwood validate` what it needs.

### The service around the policies

| rule | source | class |
|---|---|---|
| A request without a session ID fails validation if the engine holds a temporal policy | Temporal, *Policy sessions* | **guarantee**: every modelled request has a session |
| Adding or updating a temporal policy invalidates open sessions (HTTP 409) | Temporal, *Session invalidation*; Examples, *What changes* | **guarantee**: a session is judged against one policy set for its whole life, which is what Anchor's model assumes |
| The caller chooses the session ID, so a new session resets every count and sum | Temporal, *Security considerations*; Examples, *Cap how many times* | **assumption**, already modelled separately as `specs/policy/TemporalPolicy/SessionRotation` |
| A `response` is recorded "shortly after" completion | Temporal, *Sequencing actions*; Authoring and Examples, one-time approval notes | **assumption**. Unsafe in one direction; see below |
| Temporal enforcement needs the Workload Access Token on every hop, and `GetWorkloadAccessToken` on the gateway role; otherwise "enforcement fails" | Temporal, *Cross-account*, *Required IAM permissions* | **assumption**: enforcement is running. What a failure decides is not stated |
| No cross-account or cross-Region sessions | Temporal, *Cross-account and cross-Region* | out of scope |
| `LOG_ONLY` vs `ENFORCE` | Temporal, intro | out of scope. Anchor models `ENFORCE` |
| Region availability, observability | Temporal | out of scope |

## The plan's six questions, answered

**1. Partition: session only, or session and principal?** **Session only.** The pin is on
`sessionId` and on nothing else (Authoring, *Event schema*). The `count` note in Examples, which
says to correlate on `eventPrincipal` for multi-party approval, only makes sense if principals can
differ within a session, so it agrees.

**2. Quotas and the operator limit.** 20 temporal policies per engine, 3 temporal operators per
policy, 24h maximum window (Temporal, *Quotas*). The 24h cap is already Dogwood's default
`max_window`. **The 3-operator rule is under-specified.** Two `formerly` terms are "two of the
three". Whether `count for … where (formerly …)` counts as one operator or two, and whether `since`
counts as one, is not stated. Dogwood's own vocabulary does not settle it either. Its guide says
there are "exactly three" temporal operators (`formerly`, `previous`, `since`) and treats aggregates
separately, while Temporal lists `count` and `sum` among the operators. `dogwood check-parse`
counts *temporal leaves*, but a leaf is a whole `temporal` block: it reports the two-`formerly`
example as one leaf, so that is not AWS's unit either. The lint should count conservatively, and
its message should say how it counted. A real gateway would settle it (open question 2).

**3. Must a model carry more than one gateway?** **No, for every operator AgentCore documents.**
Every temporal predicate must say `eventResource: resource`, so a predicate can only match events at
the current request's gateway. A decision at gateway G is therefore a function of G's events alone,
even when one session spans several gateways (Temporal, *Cross-account* describes Gateway → Runtime →
Gateway chains carrying one token). So:

- model one gateway at a time. In that model, `eventResource: resource` is true of every event, and
  a policy scoped to another gateway simply does not apply, rather than widening;
- the lint, not the model, is what makes this safe. A policy missing the bind is refused by
  AgentCore. Anchor should flag it, not model it.

**The exception:** `formerly`, the aggregates and negated-left `since` are unaffected by
other-gateway events in the slice. **Positive-left `since` and `previous` are affected.** Under
key-local semantics, a positive left operand must hold at every position of the session's slice. An
other-gateway event in the same session is such a position, and the operand fails there, because
the `eventResource` bind excludes it (Dogwood guide `03-event-schema.md`, *Universal symmetric
pins*). `previous` likewise sees the slice's previous event, whichever gateway it came from. No
AgentCore example uses either form, and the guide's operator list (Temporal, *The Dogwood policy
language*) does not mention `previous`. **Step 4 should refuse those two forms under the AgentCore
reading**, with this reason, rather than give a one-gateway answer that is wrong for multi-gateway
sessions.

**4. The response-recording delay: what is visible to the next request?** **Not defined.** The
guide gives client discipline instead: issue a dependent request only after the prior response has
come back (Temporal, *Sequencing actions*). Anchor assumes a response is visible to the next
request, which is the disciplined client's view. **That assumption is not conservative, and in two
of AWS's patterns it fails in the unsafe direction:**

- **One-time-use approval** (`!disburse::response since approve::response`). Send two
  disbursements before the first one's response is recorded. When the second is decided, no
  `disburse::response` exists yet, so the approval has not been consumed: **ALLOW, ALLOW**. AWS's
  table says the second is DENY. The guide's note warns about waiting for the *approval* to be
  recorded. It does not warn that the *consuming* response has the same delay.
- **Cool-down** (`forbid … formerly within 1m X::response`). Two back-to-back calls are both allowed.

Patterns that permit on a response fail safe under the delay: they deny until the response lands.
Patterns that count `::request` events are unaffected, because a decision event is recorded as part
of the decision. So the delay matters exactly where a **negated or forbidding** term reads a
`response`. In those places, a policy's guarantee holds only for a client that sequences its calls,
and an agent is precisely the client nobody should assume does.

**Classification: assumption now, and a candidate to model in step 4.** A response could be
recorded at any later point, interleaved with later requests. That is a small nondeterministic step
in the model, and it would turn the paragraph above into a checked counterexample. It also bears on
the email: any trade protection built on a consumed approval inherits it.

**5. `output.*` presence, `principal is`, action naming.** `output.*` exists only for tools with a
declared output schema: lint. `principal is <Type>`: model it, as a request attribute whose domain
is the types the policy set names plus one more. Action naming: opaque strings, nothing to model.

**6. Event kinds and which decide.** `request` decides. `response` and `error` are history-only.
Same as Dogwood's default.

## Principals within a session

Because only the session is pinned, `eventPrincipal: principal` is a real correlation under
AgentCore. It is the only way to say "approved by someone other than the caller", and Examples
(*Threshold*, note) recommends it. For a model to say anything about it, a session must be able to
hold **at least two principals**. With one, the bind is always true and a "two different approvers"
claim is vacuously satisfied. Step 4 should check whether the session-pinned reading lets the
principal vary within a session today. If it does not, that is part of the AgentCore reading.

## Mutual exclusion locks out both sides

Not stated in AWS's tables, and it follows from the event model. In Examples' *Make two actions
mutually exclusive*, a request is recorded whether or not it is permitted. So:

1. `disburse_payment`: ALLOW
2. `delete_claim`: DENY, and its `request` event is recorded anyway
3. `disburse_payment` within 2m of step 2: **DENY**, because a deletion "was requested"

The same mechanism reaches rate limits and running totals: a denied request still counts toward the
`count` or `sum`, so a client that keeps retrying stays locked out. Anchor's model agrees with both
(`tests/policies/agentcore/`), and both still need `dogwood replay`.

A denied attempt at one action locks out the other for the full window. An agent that retries, or
one that probes, can block the action it was permitted to take. That may be what AWS intends, since
the example says "merely **attempting**". But it is a property of the pattern a reader of the table
would not predict. It belongs in the conformance suite as a row **we** derived, labelled as ours,
and checked with `dogwood replay` before it is stated anywhere as AgentCore's behaviour.

## Ground truth for the conformance suite (step 2)

AWS states the expected behaviour in two forms: decision tables, and prose that is just as exact
("the fourth call in a window is the first to be denied"). Both are ground truth. The rows are
AWS's. Any row we add is marked as ours.

| example | Authoring (`FundsTarget`) | Examples (`InsuranceAPI`) |
|---|---|---|
| output-to-input integrity | table, 3 rows | table, 3 rows |
| prerequisite on `::request` | table, 2 | none |
| freshness on `::response` | table, 3 | table, 3 |
| rate limit (`count`, `n > 3`) | prose: 3 allowed, 4th denied | prose: same |
| running total (`sum`) | prose: 1000 ×3 against 3000, third denied | prose: 100000 ×3 against 300000, third denied |
| one-time approval (`since`) | table, 3 | table, 3 |
| cool-down | table, 3 | prose only |
| continuous precondition | table, 4 | table, 4 |
| chain | table, 2 | prose |
| two prerequisites, any order | table, 3 | none |
| mutual exclusion | table, 2 | none |
| threshold (`count`, `n >= 2`) | table, 2 | none |
| block after denial (`::error`) | table, 2 | none |
| temporal + guardrail + Cedar | none | none. **Expected: REFUSED** (information provider) |

That is **14 examples on each page, 28 in all**. Each row is a request sequence plus an expected
decision, and becomes a test against the policy set **exactly as written**: scopes, `eventResource`
binds and all.

**Done 2026-10-02:** `tests/policies/agentcore/` and `tests/strands/agentcore_conformance.py`.
Verbatim, every case is refused. With the scope and joins stripped, all 26 checkable examples
conform on 163 expected decisions, including our rows for the delay and the mutex lockout. The
stripped run also found a parser gap, now fixed: AWS writes every aggregate as
`exists (n: Long). (AGG) == n && n > 3`, without parentheses around the body, and Anchor accepted
only the parenthesised form Dogwood's corpus uses. See the suite's README.

Dogwood's windows are **closed** (`ts(i) - ts(j) <= W`; guide `04-temporal-expressions.md`,
*Evaluation semantics*). So AWS's "after 1 minute has elapsed" means strictly more than 60s. At
exactly 60s the cool-down still forbids. The suite has that boundary as a row of ours.

Three details to carry into the transcription:

- Windows in the tables are qualitative ("within the window", "after the window elapses"). Pick
  explicit timestamps on both sides of each boundary, and record them as ours.
- Authoring's threshold example correlates `input.toAccount` with `context.input.customerId`: an
  account ID against a customer ID. It type-checks, since both are strings. Transcribe it verbatim
  and do not fix it; Examples' version uses `claimId` on both sides.
- `…inputs(A)` in the saved pages is `...inputs(A)`, and `⇐` is `<=` (ledger, scan findings).

## Open questions

1. **Session lifecycle and identity propagation.** `policy-session-based-temporal.md` is the page
   all three of the others defer to on this, and it is not among the saved pages. It should say
   whether a session can span principals and gateways in practice, and what happens at a hop that
   drops the token. **The owner would need to save it.** It then needs the usual scan and ledger
   row.
2. **How the 3-operator quota counts aggregates and `since`.** Only a real gateway settles this:
   create policies at the boundary and see which are refused. Owner's call, as in step 3.
3. **Whether the published schema is the deployed one.** Step 3 corroborates it with `dogwood`.
   Only a real gateway confirms it.
4. **What "enforcement fails" decides** when the token is missing: deny everything, or skip the
   temporal policies? The difference is fail-closed versus fail-open. Not stated anywhere in the
   four pages.

Questions 2–4 change a lint threshold or a stated assumption, not the model, so none of them blocks
step 2.
