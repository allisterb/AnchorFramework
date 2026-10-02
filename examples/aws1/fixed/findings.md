# Findings — `fixed`

**Input scan.** 6 input files scanned: clean.

**Nothing found.** Every rule is load-bearing and every stated intention holds,
within the bounds each check reports.


## What was checked

| | |
|---|---|
| policy sets | 2 |
| stated intentions (`.tla`) | 2 |
| questions answered | 0 of 0 — not asked: --no-llm |
| event-schema reading | pinned by `callerPrincipal`, Dogwood's default |

## Per policy set

| policy set | rules | verdicts |
|---|---|---|
| `07-trust-decay.dw` | 2 | live |
| `agent-policy.dw` | 7 | live |

## Stated intentions

| policy set | module | |
|---|---|---|
| `agent-policy.dw` | `TradeGate.tla` | holds |
| `07-trust-decay.dw` | `TrustDecay.tla` | holds |

### What each of them forbids

Read these before the verdicts above. Each line is the only thing its claim
can catch — a claim that forbids nothing you object to passes without having
tested what you meant.

**`TradeGate.tla`** — 5 state(s), enumerated from `Init`

- `RequiresBothChecks` forbids: the policy GRANTS it (Allowed(prereq)), and yet prereq is not "both" _(its condition applies to 0 of 5 states)_
- `ProfileAloneIsNotEnough` forbids: prereq is "profileOnly", and yet the policy GRANTS it (Allowed(prereq)) _(its condition applies to 1 of 5 states)_
- `FreshPriceAloneIsNotEnough` forbids: prereq is "freshPriceOnly", and yet the policy GRANTS it (Allowed(prereq)) _(its condition applies to 1 of 5 states)_
- `NothingAllowsNoTrade` forbids: prereq is "neither", and yet the policy GRANTS it (Allowed(prereq)) _(its condition applies to 1 of 5 states)_
- `BothIsAllowed` forbids: prereq is "both", and yet the policy REFUSES it (Allowed(prereq)) _(its condition applies to 1 of 5 states)_

**`TrustDecay.tla`** — 6 state(s), enumerated from `Init`

- `LosesWriteAfter15m` forbids: gap is greater than 15 * Minute (= 900), and yet the policy GRANTS it (TradeAllowed(gap)) _(its condition applies to 2 of 6 states)_
- `KeepsWriteWhileAdvisorEngaged` forbids: gap is at most 15 * Minute (= 900), and yet the policy REFUSES it (TradeAllowed(gap)) _(its condition applies to 4 of 6 states)_
- _defined but not named in the `.cfg`, so never checked:_ `LosesWriteAfter10m`

---

`traces/` holds the generated model, the configs and the raw TLC output for every
run above, each with a README giving the command to re-run it. `results.json` is the
same findings as data.
