# agent-policy.dw

**Stated intention.** Refunds might be issued only during business hours, defined as 9:00 AM-5:00 PM UTC, and only for amounts of $2,500 or less.

## What was checked

`BusinessHours.tla`, drafted from the intention above and kept because it caught 1 broken version(s) of this policy.

### Does it say what you asked for?

A second model, shown only the requirement and the plain-English reading of the claim — never the formal claim itself — judged that they match. That is an agreement between two models, not a proof that the claim captures the requirement.

## Verdicts

```
Policy set: agent-policy.dw
Property module: BusinessHours.tla

The property module HOLDS: every claim in it holds.

WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the states it ranges over its condition applies to:

BusinessHours

  3 claims will be checked, over 64 states:
      req = [account |-> 1, amount |-> 2500, charge_id |-> 1, systemNowTime |->
        32399999]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 1, systemNowTime |->
        32400000]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 1, systemNowTime |->
        61200000]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 1, systemNowTime |->
        61200001]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 2, systemNowTime |->
        32399999]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 2, systemNowTime |->
        32400000]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 2, systemNowTime |->
        61200000]
      req = [account |-> 1, amount |-> 2500, charge_id |-> 2, systemNowTime |->
        61200001]
      and 56 more

  OutsideBusinessHoursRefused
      says:     whenever req.systemNowTime is less than BusinessHoursMin or
                req.systemNowTime is greater than BusinessHoursMax,
                then the policy REFUSES it (RefundAllowed(req))
      forbids:  req.systemNowTime is less than BusinessHoursMin or req.systemNowTime is
                greater than BusinessHoursMax,
                and yet the policy GRANTS it (RefundAllowed(req))
      applies:  to 32 of the 64 states:
                  req = [account |-> 1, amount |-> 2500, charge_id |-> 1, systemNowTime
                    |-> 32399999]
                  req = [account |-> 1, amount |-> 2500, charge_id |-> 1, systemNowTime
                    |-> 61200001]
                  req = [account |-> 1, amount |-> 2500, charge_id |-> 2, systemNowTime
                    |-> 32399999]
                  req = [account |-> 1, amount |-> 2500, charge_id |-> 2, systemNowTime
                    |-> 61200001]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 1, systemNowTime
                    |-> 32399999]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 1, systemNowTime
                    |-> 61200001]
                  and 26 more

  OverMaxAmountRefused
      says:     whenever req.amount is greater than MaxAmount,
                then the policy REFUSES it (RefundAllowed(req))
      forbids:  req.amount is greater than MaxAmount,
                and yet the policy GRANTS it (RefundAllowed(req))
      applies:  to 16 of the 64 states:
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 1, systemNowTime
                    |-> 32399999]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 1, systemNowTime
                    |-> 32400000]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 1, systemNowTime
                    |-> 61200000]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 1, systemNowTime
                    |-> 61200001]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 2, systemNowTime
                    |-> 32399999]
                  req = [account |-> 1, amount |-> 2501, charge_id |-> 2, systemNowTime
                    |-> 32400000]
                  and 10 more

  CompliantRefundAllowed
      says:     whenever req.amount is 500 and req.systemNowTime is BusinessHoursMin and
                req.account is 1 and req.charge_id is 1,
                then the policy GRANTS it (RefundAllowed(req))
      forbids:  req.amount is 500 and req.systemNowTime is BusinessHoursMin and
                req.account is 1 and req.charge_id is 1,
                and yet the policy REFUSES it (RefundAllowed(req))
      applies:  to 1 of the 64 states:
                  req = [account |-> 1, amount |-> 500, charge_id |-> 1, systemNowTime
                    |-> 32400000]

  Read the `forbids` lines before the run, not after it. Each one is the only
  thing its claim can catch; if none of them describes something you would
  object to, the check will pass without having tested what you meant.

This says nothing about requests the property module does not name.

The derived questions were NOT attempted: this policy is outside the subset they can range over.
  REFUSED: agent-policy.dw is outside the modelled subset
  policy reads 6 input/output fields; the request space is the product of their domains, so this would explode (limit 4, raise with --max-fields)
That is a limit of those questions, not a verdict about the policy.
```

To audit the policy set with this property module, beside every other module whose header names it:

```bash
anchor check examples\aws2\agent-policy.dw --full --property examples\aws2\anchor\business-hours\BusinessHours.tla
```

## Reported

### Verification Summary

The property module **`BusinessHours.tla` held** for all 3 claims across the **64 discrete states** tested. 

No counterexamples were found within this bounded set.

---

### What Was Checked and What Held

The model checker evaluated 3 properties across a specific test grid of **64 concrete request configurations** (combinations of `account` 1, `charge_id` 1 and 2, `amount` 500, 2500, and 2501, and `systemNowTime` values 32399999, 32400000, 61200000, and 61200001):

1. **`OutsideBusinessHoursRefused`** (Held)
   * **Scope:** Applied to **32 of the 64 states** where `systemNowTime` was set outside business hours (specifically testing `32399999` and `61200001`).
   * **Result:** In all 32 tested states, the policy refused the refund request.

2. **`OverMaxAmountRefused`** (Held)
   * **Scope:** Applied to **16 of the 64 states** where `amount` was set to `2501` (exceeding the threshold of 2500).
   * **Result:** In all 16 tested states, the policy refused the refund request.

3. **`CompliantRefundAllowed`** (Held)
   * **Scope:** Applied to **exactly 1 state**: `account = 1`, `charge_id = 1`, `amount = 500`, and `systemNowTime = 32400000`.
   * **Result:** The policy granted the refund for this single request.

---

### Property Scope and Limitations

* **Narrow Positive Test:** `CompliantRefundAllowed` tests only **one single point** (`amount = 500`, `systemNowTime = 32400000`, `account = 1`, `charge_id = 1`). It does not test whether compliant requests at other valid times (e.g., between 32400000 and 61200000) or with other compliant amounts/accounts are granted.
* **Exact Bounds:** This run checked **only** the 64 discrete requests generated from the specific values listed above. It does not establish behavior for any unlisted timestamps, amounts, account IDs, or charge IDs.
* **Derived Questions Not Run:** Automated exhaustive analysis across all policy inputs was **not attempted** because the policy reads 6 input/output fields, exceeding the tool's default 4-field limit.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 311,718 | 221,866 | 9,387 | 321,105 | 135.7 |
| the review | 1,629 | 0 | 648 | 2,277 | 5.6 |
| the report | 1,776 | 0 | 1,642 | 3,418 | 11.3 |
| **3 model call(s)** | **315,123** | **221,866** | **11,677** | **326,800** | **152.6** |

Time per stage, model calls and verification together:

```
  describe          0.2s
  draft           143.3s
  preflight         0.0s
  score            17.7s
  review            5.6s
  check             0.2s
  answer           11.3s
  report            0.0s
  total           178.2s
```

Of which 152.6s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
