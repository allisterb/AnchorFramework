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

  Every value each variable takes -- nothing else is checked:
      amount   500, 2500, 2501
      nowTime  32399999, 32400000, 40000000, 61200000, 61200001

  3 claims will be checked, over 15 states:
      amount = 500, nowTime = 32399999
      amount = 500, nowTime = 32400000
      amount = 500, nowTime = 40000000
      amount = 500, nowTime = 61200000
      amount = 500, nowTime = 61200001
      amount = 2500, nowTime = 32399999
      amount = 2500, nowTime = 32400000
      amount = 2500, nowTime = 40000000
      and 7 more

  OutsideBusinessHoursRefused
      says:     whenever nowTime is less than BusinessHoursStart or nowTime is greater
                than BusinessHoursEnd,
                then the policy REFUSES it (RefundAllowed(amount, nowTime))
      forbids:  nowTime is less than BusinessHoursStart or nowTime is greater than
                BusinessHoursEnd,
                and yet the policy GRANTS it (RefundAllowed(amount, nowTime))
      applies:  to 6 of the 15 states:
                  amount = 500, nowTime = 32399999
                  amount = 500, nowTime = 61200001
                  amount = 2500, nowTime = 32399999
                  amount = 2500, nowTime = 61200001
                  amount = 2501, nowTime = 32399999
                  amount = 2501, nowTime = 61200001

  OverAmountLimitRefused
      says:     whenever amount is greater than MaxRefundAmount,
                then the policy REFUSES it (RefundAllowed(amount, nowTime))
      forbids:  amount is greater than MaxRefundAmount,
                and yet the policy GRANTS it (RefundAllowed(amount, nowTime))
      applies:  to 5 of the 15 states:
                  amount = 2501, nowTime = 32399999
                  amount = 2501, nowTime = 32400000
                  amount = 2501, nowTime = 40000000
                  amount = 2501, nowTime = 61200000
                  amount = 2501, nowTime = 61200001

  CompliantRefundAllowed
      says:     whenever amount is MaxRefundAmount and nowTime is BusinessHoursStart,
                then the policy GRANTS it (RefundAllowed(amount, nowTime))
      forbids:  amount is MaxRefundAmount and nowTime is BusinessHoursStart,
                and yet the policy REFUSES it (RefundAllowed(amount, nowTime))
      applies:  to 1 of the 15 states:
                  amount = 2500, nowTime = 32400000

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

Here is the formal verification report for **`agent-policy.dw`** against the properties defined in **`BusinessHours.tla`**.

---

### Verification Summary

All **3 claims** in the property module **held** across the **15 concrete states** evaluated. 

No counterexamples were found within this test space.

---

### Bound and Scope of the Check

The verification was strictly limited to the combinations of the following specific values:

* **`amount`**: `500`, `2500`, `2501`
* **`nowTime`**: `32399999`, `32400000`, `40000000`, `61200000`, `61200001`

**Total combinations checked:** 15 states.  
Values outside this explicit set were **not checked**.

---

### Detailed Findings by Claim

1. **`OutsideBusinessHoursRefused`** — **HELD**
   * **What was checked:** That requests submitted outside business hours are refused.
   * **Applicable states:** 6 of the 15 states (where `nowTime` is `32399999` or `61200001`, across amounts `500`, `2500`, and `2501`).
   * **Result:** The policy refused the refund in all 6 evaluated states.

2. **`OverAmountLimitRefused`** — **HELD**
   * **What was checked:** That refund requests exceeding the maximum allowed amount are refused.
   * **Applicable states:** 5 of the 15 states (where `amount = 2501`, across all 5 evaluated timestamps).
   * **Result:** The policy refused the refund in all 5 evaluated states.

3. **`CompliantRefundAllowed`** — **HELD**
   * **What was checked:** That a refund request exactly at the maximum limit (`2500`) and exactly at the start of business hours (`32400000`) is granted.
   * **Applicable states:** 1 of the 15 states (`amount = 2500, nowTime = 32400000`).
   * **Result:** The policy granted the refund for this specific state.

---

### Observations and Exclusions

* **Limited Property Scope:** The check verified only the exact boundary and sample values listed above. It does not establish policy behavior for other dollar amounts (e.g., negative amounts, 0, or values between 500 and 2500) or other timestamps during the day.
* **Derived Questions Skipped:** Automated derived questions were **not attempted**. The policy reads 6 input/output fields, exceeding the tool's configured limit of 4 fields for exhaustive state exploration. This is a limit of the exploration tool, not a failure of the policy.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 272,036 | 174,933 | 8,229 | 280,265 | 177.5 |
| the review | 1,239 | 0 | 1,155 | 2,394 | 9.6 |
| the report | 1,297 | 0 | 1,567 | 2,864 | 9.2 |
| **3 model call(s)** | **274,572** | **174,933** | **10,951** | **285,523** | **196.3** |

Time per stage, model calls and verification together:

```
  describe          0.2s
  draft           187.1s
  preflight         0.0s
  score            21.1s
  review            9.6s
  check             1.5s
  answer            9.2s
  report            0.0s
  total           228.7s
```

Of which 196.3s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
