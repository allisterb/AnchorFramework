# agent-policy.dw

**Stated intention.** A refund over $500 requires a supervisor approval for that charge within the previous 30 minutes.

## What was checked

`SupervisorApproval.tla`, drafted from the intention above and kept because it caught 2 broken version(s) of this policy.

### Does it say what you asked for?

A second model, shown only the requirement and the plain-English reading of the claim — never the formal claim itself — judged that they match. That is an agreement between two models, not a proof that the claim captures the requirement.

## Verdicts

```
Policy set: agent-policy.dw
Property module: SupervisorApproval.tla

The property module HOLDS: every claim in it holds.

WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the states it ranges over its condition applies to:

SupervisorApproval

  Every value each variable takes -- nothing else is checked:
      hasApproval     FALSE, TRUE
      approvalCharge  1, 2
      approved        FALSE, TRUE
      gap             60, 1800, 1801
      refundCharge    1, 2
      amount          499, 500, 501, 1000

  3 claims will be checked, over 192 states:
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 1, amount = 499
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 1, amount = 500
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 1, amount = 501
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 1, amount = 1000
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 2, amount = 499
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 2, amount = 500
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 2, amount = 501
      hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60, refundCharge
        = 2, amount = 1000
      and 184 more

  Over500WithoutApprovalRefused
      says:     whenever amount is greater than 500 and hasApproval does not hold or
                approved does not hold or approvalCharge is not refundCharge or gap is
                greater than 1800,
                then the policy REFUSES it (RefundAllowed)
      forbids:  amount is greater than 500 and hasApproval does not hold or approved
                does not hold or approvalCharge is not refundCharge or gap is greater
                than 1800,
                and yet the policy GRANTS it (RefundAllowed)
      applies:  to 88 of the 192 states:
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60,
                    refundCharge = 1, amount = 501
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60,
                    refundCharge = 1, amount = 1000
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60,
                    refundCharge = 2, amount = 501
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60,
                    refundCharge = 2, amount = 1000
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 1800,
                    refundCharge = 1, amount = 501
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 1800,
                    refundCharge = 1, amount = 1000
                  and 82 more

  CompliantApprovalAllowed
      says:     whenever hasApproval holds and approved holds and approvalCharge is 1
                and refundCharge is 1 and gap is 60 and amount is 501,
                then the policy GRANTS it (RefundAllowed)
      forbids:  hasApproval holds and approved holds and approvalCharge is 1 and
                refundCharge is 1 and gap is 60 and amount is 501,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  hasApproval = TRUE, approvalCharge = 1, approved = TRUE, gap = 60,
                    refundCharge = 1, amount = 501

  CompliantUnder500Allowed
      says:     whenever hasApproval does not hold and refundCharge is 1 and amount is
                500 and gap is 60 and approvalCharge is 1 and approved is FALSE (=
                FALSE),
                then the policy GRANTS it (RefundAllowed)
      forbids:  hasApproval does not hold and refundCharge is 1 and amount is 500 and
                gap is 60 and approvalCharge is 1 and approved is FALSE (= FALSE),
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  hasApproval = FALSE, approvalCharge = 1, approved = FALSE, gap = 60,
                    refundCharge = 1, amount = 500

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
anchor check examples\aws2\agent-policy.dw --full --property examples\aws2\anchor\supervisor-approval\SupervisorApproval.tla
```

## Reported

### Verification Summary

All 3 claims in the property module **SupervisorApproval.tla** held over the finite set of **192 states** evaluated for `agent-policy.dw`.

---

### Exact Bounds Checked

The verification tested combinations strictly limited to the following values (a total state space of 192 combinations):

*   **hasApproval**: `FALSE`, `TRUE`
*   **approvalCharge**: `1`, `2`
*   **approved**: `FALSE`, `TRUE`
*   **gap**: `60`, `1800`, `1801`
*   **refundCharge**: `1`, `2`
*   **amount**: `499`, `500`, `501`, `1000`

Any requests with values outside these sets (such as different refund amounts, gaps under 60 or between 60 and 1800, or other charge IDs) were not evaluated.

---

### Detailed Findings by Claim

1. **`Over500WithoutApprovalRefused`** — **HELD**
   * **What was checked:** Applied to **88 of the 192 states** where the refund amount is over 500 (`501` or `1000`) and at least one approval requirement fails (no approval present, approval marked false, charge IDs mismatch, or the gap is `1801`).
   * **Verdict:** The policy refused the refund across all 88 evaluated configurations.

2. **`CompliantApprovalAllowed`** — **HELD**
   * **What was checked:** Applied to **1 of the 192 states** — specifically: `hasApproval = TRUE`, `approved = TRUE`, `approvalCharge = 1`, `refundCharge = 1`, `gap = 60`, and `amount = 501`.
   * **Verdict:** The policy granted the refund for this specific request.

3. **`CompliantUnder500Allowed`** — **HELD**
   * **What was checked:** Applied to **1 of the 192 states** — specifically: `hasApproval = FALSE`, `approved = FALSE`, `approvalCharge = 1`, `refundCharge = 1`, `gap = 60`, and `amount = 500`.
   * **Verdict:** The policy granted the refund for this specific request.

---

### Property Observations and Coverage Notes

* **Single-State "Allowed" Properties:** Both `CompliantApprovalAllowed` and `CompliantUnder500Allowed` test only **one specific request each**. They confirm that those two exact scenarios grant a refund, but they do not check other compliant combinations (such as amounts of `499`, approved amounts of `1000`, a `gap` of `1800`, or transactions under charge ID `2`).
* **Derived Questions Skipped:** Automated derived questions were refused and not run because the policy involves 6 input/output fields, exceeding the tool's default limit of 4 fields.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 265,825 | 194,833 | 9,533 | 275,358 | 161.7 |
| the review | 1,527 | 0 | 440 | 1,967 | 4.9 |
| the report | 1,603 | 0 | 2,030 | 3,633 | 13.1 |
| **3 model call(s)** | **268,955** | **194,833** | **12,003** | **280,958** | **179.7** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft           169.8s
  preflight         0.0s
  score            19.4s
  review            4.9s
  check             0.0s
  answer           13.1s
  report            0.0s
  total           207.3s
```

Of which 179.7s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
