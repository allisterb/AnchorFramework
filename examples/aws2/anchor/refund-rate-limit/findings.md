# agent-policy.dw

**Stated intention.** The agent might attempt no more than three refunds against the same account within one hour.

## What was checked

`RefundRateLimit.tla`, drafted from the intention above and kept because it caught 2 broken version(s) of this policy.

### Does it say what you asked for?

A second model, shown only the requirement and the plain-English reading of the claim — never the formal claim itself — judged that they match. That is an agreement between two models, not a proof that the claim captures the requirement.

## Verdicts

```
Policy set: agent-policy.dw
Property module: RefundRateLimit.tla

The property module HOLDS: every claim in it holds.

WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the states it ranges over its condition applies to:

RefundRateLimit

  Every value each variable takes -- nothing else is checked:
      priorCount     2, 3
      targetAccount  1, 2
      gap            3600, 3601

  2 claims will be checked, over 8 states:
      priorCount = 2, targetAccount = 1, gap = 3600
      priorCount = 2, targetAccount = 1, gap = 3601
      priorCount = 2, targetAccount = 2, gap = 3600
      priorCount = 2, targetAccount = 2, gap = 3601
      priorCount = 3, targetAccount = 1, gap = 3600
      priorCount = 3, targetAccount = 1, gap = 3601
      priorCount = 3, targetAccount = 2, gap = 3600
      priorCount = 3, targetAccount = 2, gap = 3601

  ExceedingRateLimitRefused
      \* The agent might attempt no more than three refunds against the same account within one hour (3600s).
      \* If there are already 3 refunds on the same account within 1 hour (gap <= 3600s), the 4th refund is refused.
      says:     whenever priorCount is 3 and targetAccount is 1 and gap is at most 3600,
                then the policy REFUSES it (RefundAllowed(priorCount, targetAccount,
                gap))
      forbids:  priorCount is 3 and targetAccount is 1 and gap is at most 3600,
                and yet the policy GRANTS it (RefundAllowed(priorCount, targetAccount,
                gap))
      applies:  to 1 of the 8 states:
                  priorCount = 3, targetAccount = 1, gap = 3600

  CompliantRefundAllowed
      \* At most 3 refunds on the same account within 1 hour is allowed when prerequisites are met.
      says:     whenever priorCount is 2 and targetAccount is 1 and gap is at most 3600,
                then the policy GRANTS it (RefundAllowed(priorCount, targetAccount,
                gap))
      forbids:  priorCount is 2 and targetAccount is 1 and gap is at most 3600,
                and yet the policy REFUSES it (RefundAllowed(priorCount, targetAccount,
                gap))
      applies:  to 1 of the 8 states:
                  priorCount = 2, targetAccount = 1, gap = 3600

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
anchor check examples\aws2\agent-policy.dw --full --property examples\aws2\anchor\refund-rate-limit\RefundRateLimit.tla
```

## Reported

### Verification Summary

The model checker evaluated the property module **`RefundRateLimit.tla`** against **`agent-policy.dw`**. All claims defined in the property module **held** across the specific states evaluated. 

No counterexamples were found within the checked bounds. However, the scope of what was checked is very narrow.

---

### What Was Checked and the Bounds

The check evaluated **8 specific states** formed by the combinations of the following values:
* **`priorCount`**: 2, 3
* **`targetAccount`**: 1, 2
* **`gap`**: 3600, 3601

Nothing outside these exact values was checked.

---

### Claim Results

1. **`ExceedingRateLimitRefused`** — **HELD**
   * **What was checked:** When `priorCount` is 3, `targetAccount` is 1, and `gap` is 3600, the policy refuses the refund.
   * **Coverage:** This claim applied to and verified **1 of the 8 states** (`priorCount = 3`, `targetAccount = 1`, `gap = 3600`).

2. **`CompliantRefundAllowed`** — **HELD**
   * **What was checked:** When `priorCount` is 2, `targetAccount` is 1, and `gap` is 3600, the policy grants the refund.
   * **Coverage:** This claim applied to and verified **1 of the 8 states** (`priorCount = 2`, `targetAccount = 1`, `gap = 3600`).

---

### Property Specification Findings

While the checks passed, the properties are substantially narrower than the general rate-limiting rules described in their comments:

* **Account specificity:** Both claims explicitly hardcode `targetAccount` to `1`. Neither claim tests behavior for `targetAccount = 2` (or any other account).
* **Limited counts:** Prior refund counts of 0, 1, 4, or higher were not checked.
* **Limited time gaps:** Only exact boundary values of 3600s and 3601s were checked; other intervals (e.g., shorter gaps under an hour) were not tested.
* **Uncovered states:** Out of the 8 generated states, 6 states were not asserted on by either claim (e.g., states where `targetAccount = 2` or where `gap = 3601`).

---

### What Was Not Checked

* Any request where `targetAccount` is not 1.
* Any request where `priorCount` is not 2 or 3.
* Any request where `gap` is not 3600 or 3601.
* **Derived questions:** These were **NOT attempted**. The policy reads 6 input/output fields, exceeding the tool's default field limit of 4. This is a limit of the automated derived question generator, not a defect verdict on the policy itself.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 142,195 | 96,168 | 9,143 | 151,338 | 124.5 |
| the review | 987 | 0 | 432 | 1,419 | 5.3 |
| the report | 1,069 | 0 | 1,643 | 2,712 | 12.3 |
| **3 model call(s)** | **144,251** | **96,168** | **11,218** | **155,469** | **142.1** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft           141.2s
  preflight         0.0s
  score            35.9s
  review            5.3s
  check             0.0s
  answer           12.3s
  report            0.0s
  total           194.8s
```

Of which 142.1s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
