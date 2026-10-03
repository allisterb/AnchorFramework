# Findings — `dogwoodrepo1`

**Input scan.** 7 input files scanned: clean.

**1 thing(s) to look at.**

1. **skill-set.dw does not satisfy SuccessfulRead.tla** — with scenario = "deniedRead", the Dogwood engine ALLOWS this session at t=3, where `NoWriteAfterADeniedRead` says your policy set must REFUSE it

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
| policy sets | 2 |
| stated intentions (`.tla`) | 2 |
| questions answered | 0 of 0 — not asked: --no-llm |
| event-schema reading | pinned by `callerPrincipal`, Dogwood's default |

## Per policy set

| policy set | rules | verdicts |
|---|---|---|
| `guide-set.dw` | 3 | live |
| `skill-set.dw` | 3 | live |

## Stated intentions

| policy set | module | |
|---|---|---|
| `skill-set.dw` | `SuccessfulRead.tla` | **BROKEN** |
| `guide-set.dw` | `SuccessfulReadGuide.tla` | holds |

### What each of them forbids

Read these before the verdicts above. Each line is the only thing its claim
can catch — a claim that forbids nothing you object to passes without having
tested what you meant.

**`SuccessfulRead.tla`** — 4 state(s), enumerated from `Init`

- `NoWriteAfterADeniedRead` forbids: scenario is "deniedRead", and yet the policy GRANTS it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_
- `NoWriteAfterAFailedRead` forbids: scenario is "failedRead", and yet the policy GRANTS it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_
- `NoWriteWithoutARead` forbids: scenario is "noRead", and yet the policy GRANTS it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_
- `WriteAfterACompletedRead` forbids: scenario is "completedRead", and yet the policy REFUSES it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_

**`SuccessfulReadGuide.tla`** — 4 state(s), enumerated from `Init`

- `NoWriteAfterADeniedRead` forbids: scenario is "deniedRead", and yet the policy GRANTS it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_
- `NoWriteAfterAFailedRead` forbids: scenario is "failedRead", and yet the policy GRANTS it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_
- `NoWriteWithoutARead` forbids: scenario is "noRead", and yet the policy GRANTS it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_
- `WriteAfterACompletedRead` forbids: scenario is "completedRead", and yet the policy REFUSES it (Allowed(scenario)) _(its condition applies to 1 of 4 states)_

### The session that breaks it

Each of these is a concrete history, in Dogwood's own trace syntax, that
the policy set decides the opposite way from the claim about it. Where a
verdict is shown it is the **Dogwood engine's**, not ours — the finding
does not rest on our reading of the language.

**Every file the engine needs is kept beside each finding**, so you can run
it yourself rather than take this on trust — the trace, a Cedar schema
generated from the policy set's own actions, and a copy of the policy set. Each
directory has a README and answers for itself if you move it.

**`SuccessfulRead.tla` — NoWriteAfterADeniedRead** (`scenario = "deniedRead"`)

with scenario = "deniedRead", the Dogwood engine ALLOWS this session at t=3, where `NoWriteAfterADeniedRead` says your policy set must REFUSE it

```
@1 scope(principal: Drupe::OAuthUser::"agent", resource: Drupe::Gateway::"gw") request_context(input: { document: "restricted", user: "alice" }) Drupe::Action::"Read"::request(input: { document: "restricted", user: "alice" }, callerPrincipal: Drupe::OAuthUser::"agent", callerResource: Drupe::Gateway::"gw", requestId: "e1")
@2 scope(principal: Drupe::OAuthUser::"agent", resource: Drupe::Gateway::"gw") Drupe::Action::"Read"::error(input: { document: "restricted", user: "alice" }, callerPrincipal: Drupe::OAuthUser::"agent", callerResource: Drupe::Gateway::"gw", requestId: "e2")
@3 scope(principal: Drupe::OAuthUser::"agent", resource: Drupe::Gateway::"gw") request_context(input: { document: "restricted", user: "alice" }) Drupe::Action::"Write"::request(input: { document: "restricted", user: "alice" }, callerPrincipal: Drupe::OAuthUser::"agent", callerResource: Drupe::Gateway::"gw", requestId: "e3")
```

Run it yourself, from `traces/skill-set-SuccessfulRead/witness`:

```bash
dogwood replay --policy-schema generated.cedarschema --event-schema pinned.dwschema --trace NoWriteAfterADeniedRead.log skill-set.dw
```


---

`traces/` holds the generated model, the configs and the raw TLC output for every
run above, each with a README giving the command to re-run it. `results.json` is the
same findings as data.
