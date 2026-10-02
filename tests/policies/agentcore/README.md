# AgentCore conformance suite

AWS's own statement of how AgentCore decides, as test cases. Step 2 of the AgentCore plan
(`docs/agent/HANDOFF.md`). The rules it tests are in `docs/agentcore.md`.

Run it with:

```
python tests/strands/agentcore_conformance.py              # verbatim: the target
python tests/strands/agentcore_conformance.py --stripped   # what Anchor can check today
```

## What is here

| | |
|---|---|
| `authoring/` | the 14 examples of `policy-temporal-authoring.md`, *Use cases* (the `FundsTarget` tools) |
| `examples/` | the 14 examples of `example-policies-temporal.md` (the `InsuranceAPI` reference gateway) |
| `agentcore.dwschema` | AgentCore's event schema, transcribed from `policy-temporal-authoring.md`, *Event schema*. It is Dogwood's `session-pinned` preset with the scope fields renamed |

Both pages are in `reference/docs/`, scanned and recorded in the ledger.

## One file per example

Each `.dw` holds the example's policy text **verbatim**: gateway scope, `eventResource` joins and
all. When the example tells you to "pair with a permit" without printing one, the permit is written
in the plain form AWS prints elsewhere, and marked `// ours`. Every file is ordinary Dogwood, so
`dogwood check-parse` and, in step 3, `dogwood validate` read it as it is.

The ground truth sits in `//|` lines under the policy:

```
//| target FundsTarget
//| row aws-table: get_account_balance for an account, then transfer_funds to the same account
//| @0  request  get_account_balance  { customerId: "CUST-1" }  ALLOW aws-prose
//| @1  response get_account_balance  { customerId: "CUST-1" } -> { status: "OK", accountId: "ACC-2", ... }
//| @10 request  transfer_funds       { fromAccount: "ACC-1", toAccount: "ACC-2", amount: 100 }  ALLOW
```

- A **row** is one session: one principal (`alice`), one session ID, the gateway the policies name.
  Timestamps are seconds.
- Every **request** carries its expected decision. **Responses** and **errors** are history, and
  carry none.
- Every expectation names its **source**: `aws-table` (a decision table), `aws-prose` (AWS's text,
  as exact as a table: "the fourth call in a window is the first to be denied"), or `ours`. A
  decision takes its row's source unless the line names its own.
- `expect refused` marks an example Anchor should refuse. Both guardrail examples carry it.

## Rules the harness enforces on the ground truth itself

Before Anchor is asked anything, each row must be a history AgentCore could actually record.
Otherwise a transcription slip turns into a "disagreement" that blames the model:

- timestamps increase within a row;
- every request has an expected decision; nothing else has one;
- every response or error answers an earlier request for the same tool with the same input;
- a **response** only answers a request expected to be **ALLOWED**. An error can answer either a
  denial or a permitted call whose tool failed.

## Where the timings come from

AWS's tables are qualitative: "within the window", "after the window elapses". The timestamps are
ours. Rows tagged `ours` go further, testing what the tables leave out. Dogwood's guide gives the
semantics (`04-temporal-expressions.md`, *Evaluation semantics*). Anchor's model agrees with every
one of these rows. **They still need `dogwood replay` (step 3) before they are stated anywhere as
AgentCore's behaviour.**

| file | the row of ours tests |
|---|---|
| `authoring/03-freshness`, `07-cool-down` | windows are **closed**: a witness exactly the window's length back still counts. A cool-down of `1m` still forbids at exactly 60s |
| `authoring/04-rate-limit`, `06-budget` | a **denied** request is still recorded, so it counts toward a rate limit or a running total. A client that keeps retrying stays locked out |
| `authoring/05-one-time-approval`, `examples/06-…` | **pipelining**: a second call sent before the first one's response is recorded spends a one-time approval twice |
| `authoring/07-cool-down` | the same, for a cool-down |
| `authoring/10-mutex`, `examples/11-mutex` | a **denied** attempt at one action locks out the other for the full window |
| `authoring/14-after-denial` | the block lapses once the denial falls out of the window |

## Results, 2026-10-02

| mode | result |
|---|---|
| verbatim | **all 28 refused**: the event schema declares `eventPrincipal` / `eventResource`. This is the target for step 4 |
| `--stripped` | **all 26 checkable examples conform**, on 163 expected decisions (47 from tables, 70 from AWS's prose, 46 ours). The two guardrail examples are refused as expected |

The stripped run found one Anchor parser gap on its first run, now fixed. The parser accepted only
the `exists ((AGG) == n && …)` wrapping that Dogwood's corpus uses. Every aggregate in AWS's guide
writes the body bare, `exists (n: Long). (AGG) == n && n > 3`, which is equally legal (checked with
`dogwood check-parse`). So all six of AWS's aggregate examples had been refused.

The blog post's policies are not here. Its verbatim text, scopes included, is not saved in the
repository, and it carries no decision tables. They belong to step 5.
