# The natural-language authoring policies, checked

The policies from AWS's article [*Authoring Dogwood policies from natural language in Amazon Bedrock
AgentCore*](https://aws.amazon.com/blogs/machine-learning/authoring-dogwood-policies-from-natural-language-in-amazon-bedrock-agentcore/),
transcribed here and run through Anchor.

A second, independent set alongside [`aws1`](../aws1) — a different article, a different domain
(refunds and transfers rather than portfolio trading), and written to demonstrate *generating*
policies from prose. That last part is why it is worth checking: the article's own English sentence
sits beside each policy, so the thing a property module has to state is already written down.

**Scope note.** These are snippets from a blog post explaining a workflow, not a deployed policy
set. Nothing here is a vulnerability in a product. What it is: evidence about what can be true of a
policy that parses, validates, and passes every check that does not know what it was meant to do.

## What was found

| | |
|---|---|
| **A refused transfer spends the budget it never used** | the twelve-hour cap sums `::request`, so an attempt that was DENIED still counts against it. One rejected $60,000 request blocks every transfer for twelve hours, having moved no money. Confirmed by the Dogwood engine |
| Four of the six are **correct**, checked rather than assumed | including the two most suspicious-looking. The refund limit allows exactly three; the cap is prospective, not retrospective |
| The set is **at the edge of exhaustive search** | six input/output fields, so the request space is the product of six domains. `--max-fields 8` is required and the derived run is slow; this is where `--smoke` earns its place |
| One policy cannot be checked **at all**, correctly | policy 5 calls a Bedrock Guardrails information provider — a sandboxed script. A verdict about it would not be a function of the policy and the trace |


## The finding: attempts are not transfers

The article's sentence:

> "Block a transfer if the total amount **transferred** in the past 12 hours would exceed $50,000."

The policy beside it sums `::request`:

```dogwood
sum a for (a: Long), (t: Timepoint). where (
    formerly within 12h (
        AgentCore::Action::"initiate_transfer"::request{ input.amount: a } && tp(t)
    )
)
```

Under AgentCore's own convention the `::request` is recorded when the action is *attempted*,
whatever happens next; the outcome follows as `::response` when it completed or `::error` when it
was denied. So a refused attempt sits in the history looking exactly like a completed transfer.

Ask the engine directly — four attempts, the first over the cap:

```
@1 60000  DENY      <- over the cap on its own, so no money moves
@2     1  DENY
@3     1  DENY
@4     1  DENY
```

**Nothing was ever transferred, and the budget is gone for twelve hours.** For an agent this is a
self-inflicted denial of service that a single oversized request triggers — and an oversized request
is exactly what a prompt injection would ask for.

`CumulativeCap.tla` states the article's sentence as an invariant and it breaks:

```bash
python src/checker/properties.py examples/aws2/agent-policy.dw \
    --property examples/aws2/CumulativeCap.tla --max-fields 8 --witness
```

```
  ARefusedAttemptDoesNotConsumeTheBudget
      TLC found      scenario = "afterRefused"
      which is       @1 verify_identity::response  @2 initiate_transfer::request
                     @3 initiate_transfer::error   @4 initiate_transfer::request
      dogwood says   DENY at t=4  -- confirms the finding
```

### Why this is a defect in the policy and not in the shape

Policy 4 beside it is the **same construction** and is correct:

> "The agent might **attempt** no more than three refunds against the same account within one hour."

That requirement says *attempt*, and `::request` is the attempt — so counting requests is exactly
right there. The engine allows three and denies the fourth, as asked.

The two policies differ by one word in their English and not at all in their shape. That is what
makes this worth reporting: it is not a language pitfall to be avoided everywhere, it is a
mismatch between one sentence and one rule, and the only way to catch it is to write the sentence
down and check it.

**The fix is one word:** sum `::response` rather than `::request`, and the cap counts money that
moved. That is the same `response`/`request` distinction
[`specs/policy/TemporalPolicy`](../../specs/policy/TemporalPolicy) is built around.

## What the derived questions said, and the rule they cannot reach

```bash
anchor check examples/aws2 --full --smoke 3000 --attempts 5 --max-fields 8
```

Six of the seven rules come back **live** — each fires, none is redundant, nothing is dead. "Live"
is true of a rule that charges a budget for money that never moved, which is the whole argument for
stating intent: the built-in findings are the claims that can be made *without* knowing what a
policy was for, and this policy is wrong only relative to a sentence.

**The seventh is `unknown`, and it is the one with the defect.** That is not a coincidence and it is
worth understanding:

| rule | | |
|---|---|---|
| forbid #6, the refund rate limit | **live** | its witness is four refund attempts. At the default bound of 3 attempts it was `unknown` — the session that makes it matter is longer than the search was allowed to be. `--attempts 5` reaches it |
| forbid #5, the cumulative cap | **`unknown`, always** | no bound reaches it. Its threshold is `50000`, which is the aggregate's *comparison bound* rather than a literal any field is compared against — so `amount` gets the default domain `{1, 2}` and no session assembled from that domain can sum past the cap, however deep the walk |

So the derived checks **cannot** reach the rule that is wrong, and `CumulativeCap.tla` is not a
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
| `03-cumulative-cap.dw` | the twelve-hour $50,000 cap — **the finding** |
| `04-refund-rate-limit.dw` | three refund attempts per account per hour. Correct, and kept beside policy 3 because the pair is the argument |
| `06-supervisor-approval.dw` | a refund over $500 needs an approval for that charge within 30 minutes |
| `agent-policy.dw` | the five as a **set**, with the supporting reads permitted, which is how they would be deployed |
| `CumulativeCap.tla` / `.cfg` | the article's own sentence about the cap, stated as an invariant |

**Policy 5 is absent.** It calls `BedrockGuardrails::SensitiveInformation(...)`, an information
provider — a sandboxed Rhai script. Its result is not a function of the policy and the trace, so no
model checker can say anything true about it, and Anchor refuses rather than approximating. That is
the correct answer rather than a gap; see
[`the-modelled-subset`](../../src/Anchor.MCPServer/knowledge/the-modelled-subset.md).

**Transcription caveat.** These were transcribed from the published article and each one is
confirmed to parse by `dogwood check-parse`, which is strong evidence they are faithful and not
proof of it. The `resource` scopes and any `eventResource` joins are dropped as in `aws1` — Anchor
models actions, event kinds and input/output fields, not entity hierarchies.
