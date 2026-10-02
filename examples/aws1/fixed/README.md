# The article's policy set, corrected and checked

A proposed correction of the six parseable policies in the AWS blog post, as **one set** in
AgentCore's own form: every rule scoped to the gateway, `eventResource: resource` in every predicate.
[`agent-policy.dw`](agent-policy.dw) carries the reason for each change in its header; in short:

| the published set | the correction | answers |
|---|---|---|
| four `permit`s on `execute_trade`, each an alternative to the others | **one** `permit` for what every trade needs — integrity and freshness joined with `&&`, AgentCore's own idiom for "both prerequisites" — and **`forbid`s** for what takes access away | finding 1 |
| trust decay as `permit … unless` an advisor interacted | `forbid` on both write actions `unless` an advisor interacted in the last 15 minutes | finding 2 |
| integrity on the lookup's `input.profile_id` | on the lookup's **returned** `output.portfolio_id`. Needs `get_client_profile` to declare an output schema with that field, or AgentCore rejects the policy | finding 3 |
| the budget summing quote requests, as a `permit` | a `forbid` summing **trade** requests, including the one being decided — AgentCore's own running-total pattern | finding 4 |
| `FinTarget___` names in policy 1, bare names elsewhere | bare names throughout, matching the article's tables. Deployed, every name takes the gateway target's prefix — consistently | finding 5 |
| approval for `cost` not `< 25000` | approval for `cost > 25000`, as the prose says | the threshold |

## Checked against every table

[`../tables/90-fixed-set.dw`](../tables/90-fixed-set.dw) replays **every row of every one of the
article's tables** against this whole set. Each row supplies what the other protections need — a
recent advisor interaction, a profile lookup, a fresh quote — so that it tests exactly the protection
its own table is about. **All 68 decisions are reproduced by Anchor's model and by the Dogwood
engine**, the engine reading this file as written under AgentCore's event schema.

```bash
python tests/strands/agentcore_replay.py --suite examples/aws1/tables
python tests/strands/agentcore_conformance.py --suite examples/aws1/tables
python src/checker/properties.py examples/aws1/fixed/agent-policy.dw --property examples/aws1/fixed/EmptyTrajectory.tla
```

[`EmptyTrajectory.tla`](EmptyTrajectory.tla) is the claim the published set breaks, finding 1: a
trade with nothing before it in the session is refused. Here it holds.

## What it does not fix

**Finding 6, one approval for two trades.** An approval is consumed when a trade's `response` is
recorded, and AgentCore records a response "shortly after" the call completes. Two trades sent back
to back can both find it unconsumed. No policy closes that; the client has to wait for each response,
which is the guide's own advice. The row stays a finding in the fixed set's table.

**Two costs, stated.**

- **The budget counts denied attempts.** It sums `execute_trade` *requests*, and a denied request is
  still recorded as one. A $30,000 trade refused at the cap counts toward it, so a later small trade
  is refused too. Summing *responses* would avoid that, but would not include the trade being
  decided, which has no response yet. The guide's pattern takes the request, and so does this.
- **Any trade consumes an approval**, a small one included — as in the article's policy 5.

## What this does and does not establish

The set satisfies the article's tables, within the bounds the checks report, and validates with the
Dogwood binary built from the pinned `ext/dogwood` submodule under AgentCore's event schema and the
action schema in [`../tables/blog.cedarschema`](../tables/blog.cedarschema), which is ours. It has not
run on an AgentCore gateway. It is a proposal for the article, not a tested production policy.
