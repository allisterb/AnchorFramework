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

  3 claims will be checked, over 192 states:
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
        refund_charge = 1, gap = 60
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
        refund_charge = 1, gap = 1800
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
        refund_charge = 1, gap = 1801
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
        refund_charge = 2, gap = 60
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
        refund_charge = 2, gap = 1800
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 1,
        refund_charge = 2, gap = 1801
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 2,
        refund_charge = 1, gap = 60
      amount = 499, has_approval = FALSE, approved = FALSE, approval_charge = 2,
        refund_charge = 1, gap = 1800
      and 184 more

  Over500RequiresApproval
      says:     whenever amount is greater than 500 and ValidApproval(has_approval,
                approved, approval_charge, refund_charge, gap) does not hold,
                then the policy REFUSES it (RefundAllowed)
      forbids:  amount is greater than 500 and ValidApproval(has_approval, approved,
                approval_charge, refund_charge, gap) does not hold,
                and yet the policy GRANTS it (RefundAllowed)
      applies:  to 88 of the 192 states:
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 60
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 1800
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 1801
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 2, gap = 60
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 2, gap = 1800
                  amount = 2500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 2, gap = 1801
                  and 82 more

  ApprovedRefundIsAllowed
      says:     whenever amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 2500 and has_approval holds and approved holds and
                approval_charge is 1 and refund_charge is 1 and gap is 60,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 2500, has_approval = TRUE, approved = TRUE, approval_charge =
                    1, refund_charge = 1, gap = 60

  SmallRefundWithoutApprovalIsAllowed
      says:     whenever amount is 500 and has_approval does not hold and refund_charge
                is 1 and gap is 60 and approval_charge is 1 and approved does not hold,
                then the policy GRANTS it (RefundAllowed)
      forbids:  amount is 500 and has_approval does not hold and refund_charge is 1 and
                gap is 60 and approval_charge is 1 and approved does not hold,
                and yet the policy REFUSES it (RefundAllowed)
      applies:  to 1 of the 192 states:
                  amount = 500, has_approval = FALSE, approved = FALSE, approval_charge
                    = 1, refund_charge = 1, gap = 60

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

All 3 claims in `SupervisorApproval.tla` **held** across the **192 states** explored by the model checker. No counterexamples were found within this tested subset.

However, two of the three claims test only single, specific request configurations rather than broader conditions. Furthermore, derived general questions were not evaluated.

---

### What Was Checked and What Held

The checker evaluated combinations formed from discrete values across 6 variables:
* **`amount`**: sampled values including `499`, `500`, and `2500`
* **`has_approval`**: `TRUE`, `FALSE`
* **`approved`**: `TRUE`, `FALSE`
* **`approval_charge`**: `1`, `2`
* **`refund_charge`**: `1`, `2`
* **`gap`**: `60`, `1800`, `1801`

Total state space explored: **192 states**.

---

### Claim-by-Claim Results

#### 1. `Over500RequiresApproval`
* **Verdict:** Held.
* **Scope:** Applied to **88 of the 192 states** (specifically where `amount = 2500` and `ValidApproval(...)` is false).
* **Behavior:** In all 88 applicable states where the amount exceeded 500 without valid approval, the policy refused the refund (`RefundAllowed` was false).

#### 2. `ApprovedRefundIsAllowed`
* **Verdict:** Held.
* **Scope:** Applied to **1 of the 192 states**.
* **Finding on Property Design:** This property only tests a single point:
  * `amount = 2500`
  * `has_approval = TRUE`
  * `approved = TRUE`
  * `approval_charge = 1`
  * `refund_charge = 1`
  * `gap = 60`
  
  The property did not test whether approvals are granted for other amounts over 500, other valid charge identifiers, or other valid gap durations (e.g., `gap = 1800`).

#### 3. `SmallRefundWithoutApprovalIsAllowed`
* **Verdict:** Held.
* **Scope:** Applied to **1 of the 192 states**.
* **Finding on Property Design:** This property also tests only a single point:
  * `amount = 500`
  * `has_approval = FALSE`
  * `approved = FALSE`
  * `approval_charge = 1`
  * `refund_charge = 1`
  * `gap = 60`
  
  It did not test whether unapproved refunds are permitted for other small amounts (such as `amount = 499`) or across other charge IDs and gap values.

---

### What Was Not Checked

1. **Unchecked Request Values:** Any inputs outside the sampled values—including amounts other than `499`, `500`, and `2500`, gaps other than `60`, `1800`, and `1801`, or charge IDs other than `1` and `2`—were not evaluated.
2. **Derived General Questions:** Automated derived property checks were skipped because `agent-policy.dw` evaluates 6 input/output fields, exceeding the default 4-field limit.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 186,331 | 119,848 | 8,890 | 195,221 | 97.8 |
| the review | 1,408 | 0 | 325 | 1,733 | 4.2 |
| the report | 1,573 | 0 | 1,708 | 3,281 | 11.2 |
| **3 model call(s)** | **189,312** | **119,848** | **10,923** | **200,235** | **113.1** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft           104.3s
  preflight         0.0s
  score            15.1s
  review            4.2s
  check             0.0s
  answer           11.2s
  report            0.0s
  total           134.8s
```

Of which 113.1s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
