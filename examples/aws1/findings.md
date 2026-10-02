# Findings — `aws1`

**Input scan.** 17 input files scanned: clean.

**4 thing(s) to look at.**

1. **agent-policy.dw does not satisfy EmptyTrajectory.tla** — with amount = 1000, the Dogwood engine ALLOWS this session at t=1, where `NoTradeFromAnEmptyTrajectory` says your policy set must REFUSE it
2. **agent-policy.dw does not satisfy TradeGate.tla** — with prereq = "freshPriceOnly", the Dogwood engine ALLOWS this session at t=40, where `FreshPriceAloneIsNotEnough` says your policy set must REFUSE it
3. **07-trust-decay.dw does not satisfy TrustDecay.tla** — with gap = 1, the Dogwood engine REFUSES this session at t=2, where `KeepsWriteWhileAdvisorEngaged` says your policy set must ALLOW it
4. **07-trust-decay.dw does not satisfy TrustDecay10.tla** — with gap = 960, the Dogwood engine ALLOWS this session at t=961, where `LosesWriteAfter10m` says your policy set must REFUSE it

> **This run was `--smoke 1000`.** Each policy set was explored as 1000 random
> behaviours instead of exhaustively, because this set's request space is the product
> of its field domains and too large to exhaust. That changes what the verdicts mean:
>
> | | |
> |---|---|
> | `live` | **sound.** A witness is a witness however it was found, so the rule really does change some verdict |
> | `unknown` | **not a finding.** This walk did not reach a session where the rule matters. It does not mean the rule is inert |
>
> **VACUOUS, REDUNDANT and DEAD cannot appear in this report at all** — each is a claim
> that no session exists, and a random walk cannot establish one. To get those verdicts,
> re-run without `--smoke` and expect it to take much longer.

## What was checked

| | |
|---|---|
| policy sets | 7 |
| stated intentions (`.tla`) | 4 |
| questions answered | 0 of 5 — not asked: --no-llm |
| event-schema reading | pinned by `callerPrincipal`, Dogwood's default |

## Per policy set

| policy set | rules | verdicts |
|---|---|---|
| `01-workflow-sequencing.dw` | 2 | unknown |
| `02-output-to-input.dw` | 1 | unknown |
| `03-data-freshness.dw` | 1 | unknown |
| `04-cumulative-budget-cap.dw` | 1 | live |
| `05-human-approval.dw` | 1 | live |
| `07-trust-decay.dw` | 1 | live |
| `agent-policy.dw` | 12 | live, unknown |

## Stated intentions

| policy set | module | |
|---|---|---|
| `agent-policy.dw` | `EmptyTrajectory.tla` | **BROKEN** |
| `agent-policy.dw` | `TradeGate.tla` | **BROKEN** |
| `07-trust-decay.dw` | `TrustDecay.tla` | **BROKEN** |
| `07-trust-decay.dw` | `TrustDecay10.tla` | **BROKEN** |

### What each of them forbids

Read these before the verdicts above. Each line is the only thing its claim
can catch — a claim that forbids nothing you object to passes without having
tested what you meant.

**`EmptyTrajectory.tla`** — 2 state(s), enumerated from `Init`

- `NoTradeFromAnEmptyTrajectory` forbids: the policy GRANTS it (Allowed(amount))

**`TradeGate.tla`** — 5 state(s), enumerated from `Init`

- `FreshPriceAloneIsNotEnough` forbids: prereq is "freshPriceOnly", and yet the policy GRANTS it (Allowed(prereq)) _(its condition applies to 1 of 5 states)_
- _defined but not named in the `.cfg`, so never checked:_ `BothIsAllowed`, `NothingAllowsNoTrade`, `ProfileAloneIsNotEnough`, `RequiresBothChecks`

**`TrustDecay.tla`** — 6 state(s), enumerated from `Init`

- `LosesWriteAfter15m` forbids: gap is greater than 15 * Minute (= 900), and yet the policy GRANTS it (TradeAllowed(gap)) _(its condition applies to 2 of 6 states)_
- `KeepsWriteWhileAdvisorEngaged` forbids: gap is at most 15 * Minute (= 900), and yet the policy REFUSES it (TradeAllowed(gap)) _(its condition applies to 4 of 6 states)_
- `LosesWriteAfter10m` forbids: gap is greater than 10 * Minute (= 600), and yet the policy GRANTS it (TradeAllowed(gap)) _(its condition applies to 3 of 6 states)_

**`TrustDecay10.tla`** — 6 state(s), enumerated from `Init`

- `LosesWriteAfter10m` forbids: gap is greater than 10 * Minute (= 600), and yet the policy GRANTS it (TradeAllowed(gap)) _(its condition applies to 3 of 6 states)_

### The session that breaks it

Each of these is a concrete history, in Dogwood's own trace syntax, that
the policy set decides the opposite way from the claim about it. Where a
verdict is shown it is the **Dogwood engine's**, not ours — the finding
does not rest on our reading of the language.

**Every file the engine needs is kept beside each finding**, so you can run
it yourself rather than take this on trust — the trace, a Cedar schema
generated from the policy set's own actions, and a copy of the policy set. Each
directory has a README and answers for itself if you move it.

**`EmptyTrajectory.tla` — NoTradeFromAnEmptyTrajectory** (`amount = 1000`)

with amount = 1000, the Dogwood engine ALLOWS this session at t=1, where `NoTradeFromAnEmptyTrajectory` says your policy set must REFUSE it

```
@1 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<GATEWAY_ARN>") request_context(input: { profile_id: "client-1", cost: 1000 }, sessionId: "s1") AgentCore::Action::"execute_trade"::request(input: { profile_id: "client-1", cost: 1000 }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<GATEWAY_ARN>", requestId: "e1", sessionId: "s1")
```

Run it yourself, from `traces/agent-policy-EmptyTrajectory/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema agentcore.dwschema --trace NoTradeFromAnEmptyTrajectory.log agent-policy.dw
```

**`TradeGate.tla` — FreshPriceAloneIsNotEnough** (`prereq = "freshPriceOnly"`)

with prereq = "freshPriceOnly", the Dogwood engine ALLOWS this session at t=40, where `FreshPriceAloneIsNotEnough` says your policy set must REFUSE it

```
@11 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<GATEWAY_ARN>") AgentCore::Action::"get_market_price"::response(input: { }, output: { }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<GATEWAY_ARN>", requestId: "e1", sessionId: "s1")
@40 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<GATEWAY_ARN>") request_context(input: { profile_id: 1 }, sessionId: "s1") AgentCore::Action::"execute_trade"::request(input: { profile_id: 1 }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<GATEWAY_ARN>", requestId: "e2", sessionId: "s1")
```

Run it yourself, from `traces/agent-policy-TradeGate/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema agentcore.dwschema --trace FreshPriceAloneIsNotEnough.log agent-policy.dw
```

**`TrustDecay.tla` — KeepsWriteWhileAdvisorEngaged** (`gap = 1`)

with gap = 1, the Dogwood engine REFUSES this session at t=2, where `KeepsWriteWhileAdvisorEngaged` says your policy set must ALLOW it

```
@1 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<arn>") AgentCore::Action::"interact_advisor"::response(input: { }, output: { }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<arn>", requestId: "e1", sessionId: "s1")
@2 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<arn>") request_context(input: { }, sessionId: "s1") AgentCore::Action::"execute_trade"::request(input: { }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<arn>", requestId: "e2", sessionId: "s1")
```

Run it yourself, from `traces/07-trust-decay-TrustDecay/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema agentcore.dwschema --trace KeepsWriteWhileAdvisorEngaged.log 07-trust-decay.dw
```

**`TrustDecay10.tla` — LosesWriteAfter10m** (`gap = 960`)

with gap = 960, the Dogwood engine ALLOWS this session at t=961, where `LosesWriteAfter10m` says your policy set must REFUSE it

```
@1 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<arn>") AgentCore::Action::"interact_advisor"::response(input: { }, output: { }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<arn>", requestId: "e1", sessionId: "s1")
@961 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"<arn>") request_context(input: { }, sessionId: "s1") AgentCore::Action::"execute_trade"::request(input: { }, eventPrincipal: AgentCore::OAuthUser::"agent", eventResource: AgentCore::Gateway::"<arn>", requestId: "e2", sessionId: "s1")
```

Run it yourself, from `traces/07-trust-decay-TrustDecay10/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema agentcore.dwschema --trace LosesWriteAfter10m.log 07-trust-decay.dw
```


---

`traces/` holds the generated model, the configs and the raw TLC output for every
run above, each with a README giving the command to re-run it. `results.json` is the
same findings as data.
