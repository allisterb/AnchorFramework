# Findings — `policies`

**Input scan.** 48 input files scanned: clean.

**22 thing(s) to look at.**

1. **firewall.dw does not satisfy firewall_bad_field.tla** — a stated intention is not met
2. **firewall.dw does not satisfy firewall_unparseable.tla** — a stated intention is not met
3. **aggregate_cap.dw: DEAD forbid #2** — because `sum(...) > 100`
4. **approval_gate_response.dw: VACUOUS permit #1** — because `formerly within 1000s Approve::response`
5. **business_hours_impossible.dw: VACUOUS permit #1** — because `input.systemNowTime >= 61200000 && input.systemNowTime <= 32400000`
6. **dead_forbid.dw: DEAD forbid #2**
7. **docs_trading_forbidden.dw: DEAD forbid #1**
8. **docs_trading_forbidden.dw: VACUOUS permit #2** — because `formerly within 1h ApproveSale::response{ input.stock: 'stock', output.approved: True }`
9. **eval_join.dw: VACUOUS permit #1** — because `formerly within 15m verify_identity::response{ input.account: 'account', output.verified: True }`
10. **eval_join.dw: DEAD forbid #2**
11. **firewall.dw: DEAD forbid #2** — because `input.origin == external`
12. **firewall_noperm.dw: DEAD forbid #1**
13. **firewall_open.dw: REDUNDANT permit #1** — because `input.port == 22`
14. **like_impossible.dw could not be checked** — the checker produced no verdict
15. **long_overflow.dw could not be checked** — the checker produced no verdict
16. **order_decimal.dw: VACUOUS permit #1** — because `<exists>`
17. **order_long.dw: VACUOUS permit #1** — because `<exists>`
18. **overridden_permit.dw: VACUOUS permit #1**
19. **redundant_permit.dw: REDUNDANT permit #2**
20. **syntax_broken.dw could not be checked** — the checker produced no verdict
21. **vacuous_two_terms.dw: VACUOUS permit #1** — because `input.origin == nowhere && input.origin == local`
22. **vacuous_two_terms.dw: DEAD forbid #2**

## What was checked

| | |
|---|---|
| policy sets | 33 |
| stated intentions (`.tla`) | 5 |
| questions answered | 0 |
| event-schema reading | pinned by `callerPrincipal`, Dogwood's default |

## Modules not run

- `eval_join.tla` — its header names no policy set in this directory -- add `<policy-set>.dw` to it
- `tagged_session.tla` — its header names no policy set in this directory -- add `<policy-set>.dw` to it

## Per policy set

| policy set | rules | verdicts |
|---|---|---|
| `added_action.dw` | 2 | live |
| `aggregate_cap.dw` | 2 | DEAD, live |
| `approval_gate_error.dw` | 1 | live |
| `approval_gate_request.dw` | 1 | live |
| `approval_gate_response.dw` | 1 | VACUOUS |
| `business_hours.dw` | 1 | live |
| `business_hours_impossible.dw` | 1 | VACUOUS |
| `dead_forbid.dw` | 2 | DEAD, live |
| `docs_trading.dw` | 2 | live |
| `docs_trading_forbidden.dw` | 2 | DEAD, VACUOUS |
| `edit_diverges_both_ways.dw` | 3 | live |
| `edit_diverges_both_ways_old.dw` | 1 | live |
| `eval_join.dw` | 2 | DEAD, VACUOUS |
| `firewall.dw` | 2 | DEAD, live |
| `firewall_ip.dw` | 2 | live |
| `firewall_ip_narrow.dw` | 2 | live |
| `firewall_noperm.dw` | 1 | DEAD |
| `firewall_open.dw` | 2 | REDUNDANT, live |
| `like_impossible.dw` | — | could not be checked |
| `like_prefix.dw` | 1 | live |
| `like_two_patterns.dw` | 1 | live |
| `long_overflow.dw` | — | could not be checked |
| `order_decimal.dw` | 1 | VACUOUS |
| `order_long.dw` | 1 | VACUOUS |
| `ordering_live.dw` | 1 | live |
| `overridden_permit.dw` | 2 | VACUOUS, live |
| `redundant_permit.dw` | 2 | REDUNDANT, live |
| `redundant_permit_minimal.dw` | 1 | live |
| `scope_bind.dw` | 1 | live |
| `session_gate.dw` | 1 | live |
| `string_output.dw` | 2 | live |
| `syntax_broken.dw` | — | could not be checked |
| `vacuous_two_terms.dw` | 2 | DEAD, VACUOUS |

## Stated intentions

| policy set | module | |
|---|---|---|
| `aggregate_cap.dw` | `aggregate_cap.tla` | holds |
| `firewall.dw` | `firewall.tla` | holds |
| `firewall.dw` | `firewall_bad_field.tla` | **BROKEN** |
| `firewall_ip.dw` | `firewall_ip.tla` | holds |
| `firewall.dw` | `firewall_unparseable.tla` | **BROKEN** |

### What each of them forbids

Read these before the verdicts above. Each line is the only thing its claim
can catch — a claim that forbids nothing you object to passes without having
tested what you meant.

**`aggregate_cap.tla`** — 2 state(s), enumerated from `Init`

- `OverTheCapIsRefused` forbids: amount is greater than 100, and yet the policy GRANTS it (Allowed(amount)) _(its condition applies to 1 of 2 states)_
- `UnderTheCapIsAllowed` forbids: amount is at most 100, and yet the policy REFUSES it (Allowed(amount)) _(its condition applies to 1 of 2 states)_

**`firewall.tla`** — 4 state(s), enumerated from `Init`

- `LocalSshIsAllowed` forbids: req.port is 22 and req.origin is "local", and yet the policy REFUSES it (Grants(req)) _(its condition applies to 1 of 4 states)_
- `OutsideIsRefused` forbids: req.origin is "external", and yet the policy GRANTS it (Grants(req)) _(its condition applies to 2 of 4 states)_

**`firewall_bad_field.tla`** — 4 state(s), enumerated from `Init`

- `LocalSshIsAllowed` forbids: req.nosuchfield is 22 and req.origin is "local", and yet the policy REFUSES it (Grants(req)) _(its condition applies to 0 of 4 states)_
- `OutsideIsRefused` forbids: req.origin is "external", and yet the policy GRANTS it (Grants(req)) _(its condition applies to 2 of 4 states)_

**`firewall_ip.tla`** — 5 state(s), enumerated from `Init`

- `BlockedRangeIsRefused` forbids: D!InRange(req.src.v, <<10, 0, 0, 0>>, 8) holds, and yet the policy GRANTS it (Grants(req)) _(its condition applies to 0 of 5 states)_

**`firewall_unparseable.tla`** — 4 state(s), enumerated from `Init`

- `LocalSshIsAllowed` forbids: req.port is 22 and req.origin is "local", and yet the policy REFUSES it (Grants(req)) _(its condition applies to 1 of 4 states)_
- `OutsideIsRefused` forbids: req.origin is "external", and yet the policy GRANTS it (Grants(req)) _(its condition applies to 2 of 4 states)_

---

`traces/` holds the generated model, the configs and the raw TLC output for every
run above, each with a README giving the command to re-run it. `results.json` is the
same findings as data.
