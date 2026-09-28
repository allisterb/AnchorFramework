# Findings — `aws1`

**Input scan.** 15 input files scanned: clean.

**7 thing(s) to look at.**

1. **agent-policy.dw does not satisfy TradeGate.tla** — with prereq = "freshPriceOnly", the Dogwood engine ALLOWS this session at t=40, where `FreshPriceAloneIsNotEnough` says your policy set must REFUSE it
2. **07-trust-decay.dw does not satisfy TrustDecay.tla** — with gap = 1, the Dogwood engine REFUSES this session at t=2, where `KeepsWriteWhileAdvisorEngaged` says your policy set must ALLOW it
3. **07-trust-decay.dw does not satisfy TrustDecay10.tla** — with gap = 960, the Dogwood engine ALLOWS this session at t=961, where `LosesWriteAfter10m` says your policy set must REFUSE it
4. **01-workflow-sequencing.dw: VACUOUS permit #1** — because `formerly within 5m get_client_profile::response`
5. **01-workflow-sequencing.dw: VACUOUS permit #2** — because `formerly within 5m load_portfolio::response`
6. **02-output-to-input.dw: VACUOUS permit #1** — because `formerly within 24h get_client_profile::response{ input.profile_id: 'profile_id' }`
7. **03-data-freshness.dw: VACUOUS permit #1** — because `formerly within 30s get_market_price::response`

## What was checked

| | |
|---|---|
| policy sets | 7 |
| stated intentions (`.tla`) | 3 |
| questions answered | 0 |
| event-schema reading | pinned by `callerPrincipal`, Dogwood's default |

## Per policy set

| policy set | rules | verdicts |
|---|---|---|
| `01-workflow-sequencing.dw` | 2 | VACUOUS |
| `02-output-to-input.dw` | 1 | VACUOUS |
| `03-data-freshness.dw` | 1 | VACUOUS |
| `04-cumulative-budget-cap.dw` | 1 | live |
| `05-human-approval.dw` | 1 | live |
| `07-trust-decay.dw` | 1 | live |
| `agent-policy.dw` | 7 | live |

## Stated intentions

| policy set | module | |
|---|---|---|
| `agent-policy.dw` | `TradeGate.tla` | **BROKEN** |
| `07-trust-decay.dw` | `TrustDecay.tla` | **BROKEN** |
| `07-trust-decay.dw` | `TrustDecay10.tla` | **BROKEN** |

### What each of them forbids

Read these before the verdicts above. Each line is the only thing its claim
can catch — a claim that forbids nothing you object to passes without having
tested what you meant.

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

**`TradeGate.tla` — FreshPriceAloneIsNotEnough** (`prereq = "freshPriceOnly"`)

with prereq = "freshPriceOnly", the Dogwood engine ALLOWS this session at t=40, where `FreshPriceAloneIsNotEnough` says your policy set must REFUSE it

```
@11 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") AgentCore::Action::"get_market_price"::response(input: { }, output: { }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e1")
@40 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") request_context(input: { profile_id: 1 }) AgentCore::Action::"execute_trade"::request(input: { profile_id: 1 }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e2")
```

Run it yourself, from `traces/agent-policy-TradeGate/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema pinned.dwschema --trace FreshPriceAloneIsNotEnough.log agent-policy.dw
```

**`TrustDecay.tla` — KeepsWriteWhileAdvisorEngaged** (`gap = 1`)

with gap = 1, the Dogwood engine REFUSES this session at t=2, where `KeepsWriteWhileAdvisorEngaged` says your policy set must ALLOW it

```
@1 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") AgentCore::Action::"interact_advisor"::response(input: { }, output: { }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e1")
@2 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") request_context(input: { }) AgentCore::Action::"execute_trade"::request(input: { }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e2")
```

Run it yourself, from `traces/07-trust-decay-TrustDecay/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema pinned.dwschema --trace KeepsWriteWhileAdvisorEngaged.log 07-trust-decay.dw
```

**`TrustDecay10.tla` — LosesWriteAfter10m** (`gap = 960`)

with gap = 960, the Dogwood engine ALLOWS this session at t=961, where `LosesWriteAfter10m` says your policy set must REFUSE it

```
@1 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") AgentCore::Action::"interact_advisor"::response(input: { }, output: { }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e1")
@961 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") request_context(input: { }) AgentCore::Action::"execute_trade"::request(input: { }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e2")
```

Run it yourself, from `traces/07-trust-decay-TrustDecay10/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema pinned.dwschema --trace LosesWriteAfter10m.log 07-trust-decay.dw
```


---

`traces/` holds the generated model, the configs and the raw TLC output for every
run above, each with a README giving the command to re-run it. `results.json` is the
same findings as data.
