# Findings — `aws2`

**Input scan.** 9 input files scanned: clean.

**1 thing(s) to look at.**

1. **agent-policy.dw does not satisfy CumulativeCap.tla** — with scenario = "afterRefused", the Dogwood engine REFUSES this session at t=4, where `ARefusedAttemptDoesNotConsumeTheBudget` says your policy set must ALLOW it

> **This run was `--smoke 3000`.** Each policy set was explored as 3000 random
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
| policy sets | 6 |
| stated intentions (`.tla`) | 1 |
| questions answered | 0 |
| event-schema reading | pinned by `callerPrincipal`, Dogwood's default |

## Per policy set

| policy set | rules | verdicts |
|---|---|---|
| `01-business-hours.dw` | 1 | live |
| `02-identity-verification.dw` | 1 | unknown |
| `03-cumulative-cap.dw` | 1 | unknown |
| `04-refund-rate-limit.dw` | 1 | unknown |
| `06-supervisor-approval.dw` | 1 | unknown |
| `agent-policy.dw` | 7 | live, unknown |

## Stated intentions

| policy set | module | |
|---|---|---|
| `agent-policy.dw` | `CumulativeCap.tla` | **BROKEN** |

### What each of them forbids

Read these before the verdicts above. Each line is the only thing its claim
can catch — a claim that forbids nothing you object to passes without having
tested what you meant.

**`CumulativeCap.tla`** — 2 state(s), enumerated from `Init`

- `ARefusedAttemptDoesNotConsumeTheBudget` forbids: the policy REFUSES it (Allowed(scenario))

### The session that breaks it

Each of these is a concrete history, in Dogwood's own trace syntax, that
the policy set decides the opposite way from the claim about it. Where a
verdict is shown it is the **Dogwood engine's**, not ours — the finding
does not rest on our reading of the language.

**Every file the engine needs is kept beside each finding**, so you can run
it yourself rather than take this on trust — the trace, a Cedar schema
generated from the policy set's own actions, and a copy of the policy set. Each
directory has a README and answers for itself if you move it.

**`CumulativeCap.tla` — ARefusedAttemptDoesNotConsumeTheBudget** (`scenario = "afterRefused"`)

with scenario = "afterRefused", the Dogwood engine REFUSES this session at t=4, where `ARefusedAttemptDoesNotConsumeTheBudget` says your policy set must ALLOW it

```
@1 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") AgentCore::Action::"verify_identity"::response(input: { account: "a1" }, output: { verified: true }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e1")
@2 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") request_context(input: { account: "a1", amount: 60000 }) AgentCore::Action::"initiate_transfer"::request(input: { account: "a1", amount: 60000 }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e2")
@3 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") AgentCore::Action::"initiate_transfer"::error(input: { account: "a1", amount: 60000 }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e3")
@4 scope(principal: AgentCore::OAuthUser::"agent", resource: AgentCore::Gateway::"gw") request_context(input: { account: "a1", amount: 1 }) AgentCore::Action::"initiate_transfer"::request(input: { account: "a1", amount: 1 }, callerPrincipal: AgentCore::OAuthUser::"agent", callerResource: AgentCore::Gateway::"gw", requestId: "e4")
```

Run it yourself, from `traces/agent-policy-CumulativeCap/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema pinned.dwschema --trace ARefusedAttemptDoesNotConsumeTheBudget.log agent-policy.dw
```


---

`traces/` holds the generated model, the configs and the raw TLC output for every
run above, each with a README giving the command to re-run it. `results.json` is the
same findings as data.
