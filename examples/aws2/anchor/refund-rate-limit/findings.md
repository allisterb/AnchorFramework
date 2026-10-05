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

  2 claims will be checked, over 80 states:
      priorCount = 0, priorAcc = 1, targetAcc = 1, gap = 600
      priorCount = 0, priorAcc = 1, targetAcc = 1, gap = 1800
      priorCount = 0, priorAcc = 1, targetAcc = 1, gap = 3600
      priorCount = 0, priorAcc = 1, targetAcc = 1, gap = 3601
      priorCount = 0, priorAcc = 1, targetAcc = 1, gap = 7200
      priorCount = 0, priorAcc = 1, targetAcc = 2, gap = 600
      priorCount = 0, priorAcc = 1, targetAcc = 2, gap = 1800
      priorCount = 0, priorAcc = 1, targetAcc = 2, gap = 3600
      and 72 more

  FourthRefundWithinHourRefused
      says:     whenever priorCount is 3 and priorAcc is targetAcc and gap is at most
                Hour,
                then the policy REFUSES it (RefundAllowed(priorCount, priorAcc,
                targetAcc, gap))
      forbids:  priorCount is 3 and priorAcc is targetAcc and gap is at most Hour,
                and yet the policy GRANTS it (RefundAllowed(priorCount, priorAcc,
                targetAcc, gap))
      applies:  to 6 of the 80 states:
                  priorCount = 3, priorAcc = 1, targetAcc = 1, gap = 600
                  priorCount = 3, priorAcc = 1, targetAcc = 1, gap = 1800
                  priorCount = 3, priorAcc = 1, targetAcc = 1, gap = 3600
                  priorCount = 3, priorAcc = 2, targetAcc = 2, gap = 600
                  priorCount = 3, priorAcc = 2, targetAcc = 2, gap = 1800
                  priorCount = 3, priorAcc = 2, targetAcc = 2, gap = 3600

  CompliantRefundAllowed
      says:     whenever priorCount is 0 and priorAcc is 1 and targetAcc is 1 and gap is
                600,
                then the policy GRANTS it (RefundAllowed(priorCount, priorAcc,
                targetAcc, gap))
      forbids:  priorCount is 0 and priorAcc is 1 and targetAcc is 1 and gap is 600,
                and yet the policy REFUSES it (RefundAllowed(priorCount, priorAcc,
                targetAcc, gap))
      applies:  to 1 of the 80 states:
                  priorCount = 0, priorAcc = 1, targetAcc = 1, gap = 600

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

Here is the formal verification report for **`agent-policy.dw`** against the **`RefundRateLimit.tla`** property module.

---

### Verification Summary
* **Result:** **HELD** across all evaluated states.
* **Scope Tested:** A discrete state space of **80 specific configurations** combining select values of `priorCount`, `priorAcc`, `targetAcc`, and `gap` (including gaps of 600s, 1800s, 3600s, 3601s, 7200s, and account IDs 1 and 2).

---

### What Was Checked and What Held

1. **`FourthRefundWithinHourRefused` — HELD**
   * **Rule Checked:** If a user already has 3 prior refunds on the same target account within an hour (`gap <= 3600`), the policy must refuse the refund request.
   * **Exact Scope Tested:** This condition applied to and held across **6 specific states** out of the 80:
     * `priorCount = 3`, `priorAcc = 1`, `targetAcc = 1`, with `gap` $\in$ {600, 1800, 3600}
     * `priorCount = 3`, `priorAcc = 2`, `targetAcc = 2`, with `gap` $\in$ {600, 1800, 3600}

2. **`CompliantRefundAllowed` — HELD**
   * **Rule Checked:** A clean refund request (`priorCount = 0`, `gap = 600`) on account 1 is granted.
   * **Exact Scope Tested:** This claim applies to and held across **exactly 1 state** out of the 80:
     * `priorCount = 0`, `priorAcc = 1`, `targetAcc = 1`, `gap = 600`

---

### Findings on Property Design and Verification Limits

* **Narrow Positive Verification (`CompliantRefundAllowed`):**
  The property module only checks that a refund is granted in **one exact scenario** (`priorCount = 0`, `priorAcc = 1`, `targetAcc = 1`, `gap = 600`). It does not test whether requests are permitted when:
  * `priorCount` is 1 or 2.
  * The account ID is 2.
  * The time gap exceeds 1 hour (`gap = 3601` or `7200`) after prior refunds.
  * The target account differs from the prior account (`priorAcc != targetAcc`).

* **Explicit Boundaries of the Check:**
  Verification was strictly limited to the **80 combinations** generated from the property's discrete inputs (accounts 1 and 2; counts 0 through 3; gaps 600, 1800, 3600, 3601, 7200). It did not evaluate any other account identifiers, timestamps/gaps, or prior counts above 3.

* **Derived Questions Not Attempted:**
  Broader derived automated checks were not executed because the policy reads 6 input/output fields, which exceeded the checker's current threshold of 4 fields (`--max-fields`). This is a tool exploration limit, not a policy failure.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 194,934 | 135,068 | 7,708 | 202,642 | 106.6 |
| the review | 980 | 0 | 394 | 1,374 | 4.6 |
| the report | 1,151 | 0 | 1,688 | 2,839 | 11.4 |
| **3 model call(s)** | **197,065** | **135,068** | **9,790** | **206,855** | **122.5** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft           114.1s
  preflight         0.0s
  score            17.6s
  review            4.6s
  check             0.0s
  answer           11.4s
  report            0.0s
  total           147.8s
```

Of which 122.5s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
