# The natural-language authoring policies, checked

The policies from AWS's article [*Authoring Dogwood policies from natural language in Amazon Bedrock
AgentCore*](https://aws.amazon.com/blogs/machine-learning/authoring-dogwood-policies-from-natural-language-in-amazon-bedrock-agentcore/),
verbatim, and checked under AgentCore's own semantics by Anchor and by the Dogwood engine.

A second, independent set alongside [`aws1`](../aws1) — a different article, a different domain
(refunds and transfers rather than portfolio trading), and written to demonstrate *generating*
policies from prose. That last part is why it is worth checking: the article's own English sentence
sits beside each policy, so the thing a property module has to state is already written down.

**Scope note.** These are snippets from a blog post explaining a workflow, not a deployed policy
set. Nothing here is a vulnerability in a product. What it is: evidence about what can be true of a
policy that parses, validates, and passes every check that does not know what it was meant to do.

## The source

Every policy here is **the article's listing verbatim**: checked byte for byte, modulo whitespace and
comments, against the published page on 2026-10-02. The page and a PDF of it are in the reference
ledger. Policy 5 is absent, because it calls an information provider (below).

The article also prints its agent's **tool table**, giving each tool's arguments and return values
with their types. [`tables/bank.cedarschema`](tables/bank.cedarschema) is that table as a Cedar
action schema, which is what the Dogwood engine needs to replay these policies. Unlike `aws1`'s, it
is the article's schema and not a reconstruction.

## What was found

Checked under **AgentCore's own semantics**: history kept per session, AgentCore's event schema, and
AgentCore's creation-time rules. Until 2026-10-02 this example was checked under Dogwood's default
reading, history per principal, which is not what an AgentCore gateway does. The first finding below
is invisible under that reading.

| | |
|---|---|
| **The 12-hour cap is a per-session cap** | AgentCore keeps history per session, and the caller chooses the session ID. Two $40,000 transfers in one session: the second is blocked. The same two with the second in a new session: **both allowed, $80,000 in 12 hours**. Confirmed by the Dogwood engine. The refund rate limit has the same construction |
| **AgentCore would refuse to create four of the five policies** | every temporal predicate must bind `eventResource: resource` (AgentCore Developer Guide), and none here does. `dogwood validate`, which the article says checks every generated policy, accepts them, because the rule is AgentCore's and not Dogwood's |
| **A refused transfer still counts against the cap** — **the article's stated choice** | the cap sums `::request`, so a refused $60,000 attempt blocks a $1 transfer for 12 hours although nothing moved. The article says so itself: it sums attempts as "the safer reading for a cap". Recorded here as the cost of that reading, not as a defect |
| One policy cannot be checked **at all**, correctly | policy 5 calls a Bedrock Guardrails information provider, a sandboxed script. A verdict about it would not be a function of the policy and the trace |

```bash
python tests/strands/agentcore_replay.py --suite examples/aws2/tables
python tests/strands/agentcore_conformance.py --suite examples/aws2/tables --stripped
```

[`tables/agent-policy-sessions.dw`](tables/agent-policy-sessions.dw) holds the set and these
rows. The engine and Anchor's model agree on all 11 decisions, including the per-session finding.

### 1. The cap resets with the session

> "Block a transfer if the total amount transferred in the past 12 hours would exceed $50,000."

The article knows where enforcement stops. Explaining which rules its authoring pipeline sets aside,
it gives "at most ten transfers per day, counted across all of that customer's concurrent sessions"
as one that is "outside the scope of enforcement", because "Enforcement evaluates a trajectory within
a session". And of the identity check it says "the history examined is the current session's".

The 12-hour cap is that kind of rule, and it was translated anyway, with no caveat. On AgentCore the
generated policy caps **each session** at $50,000 in 12 hours, and a caller who starts a new session
starts a new $50,000. The AgentCore guide says this of every session-scoped limit: it "is not a
security control against a determined caller" (*Temporal policies*, Security considerations).

| two $40,000 transfers, same principal | second transfer |
|---|---|
| AgentCore's schema, one session | DENY |
| **AgentCore's schema, a new session** | **ALLOW** |
| Dogwood's default reading, a new session | DENY |

The third row is why this was not found before. Under Dogwood's default reading history is kept per
principal, so the cap holds across sessions, and that was the reading this example used to be
checked under.

The refund rate limit — "no more than three refunds against the same account within one hour" — is
the same construction, a count over the session's history, and resets the same way. It is not
separately replayed here, because a refund also needs the business-hours clock, which the trace
format does not carry.

### 2. Rejected by AgentCore as written

The AgentCore Developer Guide says every temporal predicate must include `eventResource: resource`,
and that omitting it "is rejected with `temporal predicates do not constrain the matched event to
the current request's resource`". None of this article's four temporal policies includes it.
Checked under AgentCore's schema, Anchor reports exactly that:

```bash
python src/checker/properties.py examples/aws2/agent-policy.dw --event-schema src/translator/agentcore.dwschema
```

```
REJECTED BY AGENTCORE: agent-policy.dw could not be created as written, so nothing was checked
  permit #4 (initiate_transfer): the predicate on verify_identity::response has no `eventResource: resource` ...
```

The article says every generated policy "is validated using the same Dogwood command-line tools
that ship with the open source language". That is true, and it is why this got through:
`dogwood validate` accepts all four, because the rule is AgentCore's, not Dogwood's. Either the
guide's rule is newer than the article, or validating with Dogwood's tools does not establish that
AgentCore will create a policy. Which of the two is the case is a question for AWS.

### 3. Attempts are not transfers — and the article says so

> "Block a transfer if the total amount **transferred** in the past 12 hours would exceed $50,000."

The policy sums `::request`, so a refused attempt sits in the history looking exactly like a
completed transfer. One rejected $60,000 request blocks every transfer for twelve hours, having
moved no money. For an agent that is a self-inflicted denial of service, triggered by exactly the
oversized request a prompt injection would ask for.

**This example used to report that as a defect. The article answers it directly:** the document
"says 'transferred' without saying whether a blocked or failed attempt counts", and "the translation
sums ::request events, meaning every transfer the agent attempted, which is the safer reading for a
cap". Its first best practice is to say which one is meant. That is a stated choice, and a defensible
one: counting attempts can never let more money through than counting completions. What the article
does not mention is the cost above, which is why it stays here, as a cost rather than a finding.

`CumulativeCap.tla` states the sentence the other way, with completed transfers, and it breaks, as it
should under the article's choice:

```bash
python src/checker/properties.py examples/aws2/agent-policy.dw \
    --property examples/aws2/CumulativeCap.tla --max-fields 8 --witness
```

Policy 4 beside it is the same construction and is right on any reading: its sentence says
"attempt", and `::request` is the attempt. The engine allows three and denies the fourth.

## What the derived questions said, and the rule they cannot reach

```bash
anchor check examples/aws2 --full --smoke 3000 --attempts 5 --max-fields 8
```

Six of the seven rules come back **live** — each fires, none is redundant, nothing is dead. "Live"
is true of a rule that charges a budget for money that never moved, which is the whole argument for
stating intent: the built-in findings are the claims that can be made *without* knowing what a
policy was for, and this policy is wrong only relative to a sentence.

**The seventh is `unknown`, and it is the cap, which both findings 1 and 3 are about.** That is not a
coincidence and it is worth understanding:

| rule | | |
|---|---|---|
| forbid #6, the refund rate limit | **live** | its witness is four refund attempts. At the default bound of 3 attempts it was `unknown` — the session that makes it matter is longer than the search was allowed to be. `--attempts 5` reaches it |
| forbid #5, the cumulative cap | **`unknown`, always** | no bound reaches it. Its threshold is `50000`, which is the aggregate's *comparison bound* rather than a literal any field is compared against — so `amount` gets the default domain `{1, 2}` and no session assembled from that domain can sum past the cap, however deep the walk |

So the derived checks **cannot** reach the cap, and `CumulativeCap.tla` is not a
nicety here — it is the only thing that can state a session carrying `Num(60000)`. That is exactly
what `PolicyUnderTest` offering no `Inputs` is for: a claim about values the policy never names has
to bring its own.

**`unknown` is not a finding**, and the report says so at the top in those words. A smoke sweep
reports `live` or `unknown` and can never report VACUOUS, REDUNDANT or DEAD — those are claims that
no session exists, and a random walk cannot establish one.

Run a single fragment and it is DEAD or VACUOUS instead, for the composition reason
[`aws1`](../aws1) documents: a forbid alone in a file has no permit to override, and a permit gated
on `X::response` cannot fire where nothing permits `X`. The blame line says so directly —
*"the condition is not why -- it is inert even with no condition at all"*.

## The files

| | |
|---|---|
| `01-business-hours.dw` | refunds in hours and under $2,500. Uses `context.system.now.toTime()`, which is what the wall-clock support was added for |
| `02-identity-verification.dw` | a transfer needs identity verified for that account within 15 minutes |
| `03-cumulative-cap.dw` | the twelve-hour $50,000 cap: findings 1 and 3 |
| `04-refund-rate-limit.dw` | three refund attempts per account per hour. Right about attempts, which its sentence names; per session on AgentCore, like the cap (finding 1) |
| `06-supervisor-approval.dw` | a refund over $500 needs an approval for that charge within 30 minutes |
| `agent-policy.dw` | the five as a **set**, with the supporting reads permitted, which is how they would be deployed |
| `CumulativeCap.tla` / `.cfg` | the article's sentence about the cap, read as completed transfers, stated as an invariant |
| [`tables/`](tables) | `agent-policy-sessions.dw`, the set against the cap's rows across sessions; and `bank.cedarschema`, the article's tool table as an action schema |

**Policy 5 is absent.** It calls `BedrockGuardrails::SensitiveInformation(...)`, an information
provider — a sandboxed Rhai script. Its result is not a function of the policy and the trace, so no
model checker can say anything true about it, and Anchor refuses rather than approximating. That is
the correct answer rather than a gap; see
[`the-modelled-subset`](../../src/Anchor.MCPServer/knowledge/the-modelled-subset.md).

**Verbatim.** Each policy file matches the published listing exactly, modulo whitespace and comments,
checked against the live page on 2026-10-02. As published these policies have no gateway scope and
no `eventResource` joins, so there was nothing to drop; finding 2 is about that absence.