# agent-policy.dw

**Stated intention.** Block a transfer if the total amount transferred in the past 12 hours would exceed $50,000.

## What was checked

`CumulativeCap.tla`, drafted from the intention above and kept because it caught 2 broken version(s) of this policy.

### Does it say what you asked for?

A second model, shown only the requirement and the plain-English reading of the claim — never the formal claim itself — judged that they match. That is an agreement between two models, not a proof that the claim captures the requirement.

## Verdicts

```
Policy set: agent-policy.dw
Property module: CumulativeCap.tla

The property module HOLDS: every claim in it holds.

WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the states it ranges over its condition applies to:

CumulativeCap

  Every value each variable takes -- nothing else is checked:
      prevAmount     30000
      currentAmount  20000, 20001, 50000, 50001
      gap            300, 43200, 43201

  2 claims will be checked, over 12 states:
      prevAmount = 30000, currentAmount = 20000, gap = 300
      prevAmount = 30000, currentAmount = 20000, gap = 43200
      prevAmount = 30000, currentAmount = 20000, gap = 43201
      prevAmount = 30000, currentAmount = 20001, gap = 300
      prevAmount = 30000, currentAmount = 20001, gap = 43200
      prevAmount = 30000, currentAmount = 20001, gap = 43201
      prevAmount = 30000, currentAmount = 50000, gap = 300
      prevAmount = 30000, currentAmount = 50000, gap = 43200
      and 4 more

  ExceedingCapIsBlocked
      says:     whenever gap is at most Window and prevAmount + currentAmount is greater
                than Cap or gap is greater than Window and currentAmount is greater than
                Cap,
                then the policy REFUSES it (TransferAllowed)
      forbids:  gap is at most Window and prevAmount + currentAmount is greater than Cap
                or gap is greater than Window and currentAmount is greater than Cap,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 7 of the 12 states:
                  prevAmount = 30000, currentAmount = 20001, gap = 300
                  prevAmount = 30000, currentAmount = 20001, gap = 43200
                  prevAmount = 30000, currentAmount = 50000, gap = 300
                  prevAmount = 30000, currentAmount = 50000, gap = 43200
                  prevAmount = 30000, currentAmount = 50001, gap = 300
                  prevAmount = 30000, currentAmount = 50001, gap = 43200
                  and 1 more

  CompliantTransferIsAllowed
      says:     whenever gap is 300 and prevAmount is 30000 and currentAmount is 20000,
                then the policy GRANTS it (TransferAllowed)
      forbids:  gap is 300 and prevAmount is 30000 and currentAmount is 20000,
                and yet the policy REFUSES it (TransferAllowed)
      applies:  to 1 of the 12 states:
                  prevAmount = 30000, currentAmount = 20000, gap = 300

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
anchor check examples\aws2\agent-policy.dw --full --property examples\aws2\anchor\cumulative-cap\CumulativeCap.tla
```

## Reported

### Verification Summary

The model checker evaluated the **`CumulativeCap.tla`** property module against **`agent-policy.dw`**. All claims defined in the module **held** across the specific states evaluated.

---

### Concrete Bounds Checked

The verification was strictly limited to **12 concrete states** formed by the combinations of the following variable values:

* **`prevAmount`**: `30000` (only 1 value tested)
* **`currentAmount`**: `20000`, `20001`, `50000`, `50001` (4 values tested)
* **`gap`**: `300`, `43200`, `43201` (3 values tested)

No other values, amounts, or time gaps were checked.

---

### Claim Results

1. **`ExceedingCapIsBlocked`** — **HELD**
   * **What it checked:** Ensures the policy refuses `TransferAllowed` whenever the transfer exceeds the cap (either within the window when `prevAmount + currentAmount > Cap`, or outside the window when `currentAmount > Cap`).
   * **Scope:** Applied to and held across **7 of the 12 states**:
     * `prevAmount = 30000, currentAmount = 20001, gap = 300`
     * `prevAmount = 30000, currentAmount = 20001, gap = 43200`
     * `prevAmount = 30000, currentAmount = 50000, gap = 300`
     * `prevAmount = 30000, currentAmount = 50000, gap = 43200`
     * `prevAmount = 30000, currentAmount = 50001, gap = 300`
     * `prevAmount = 30000, currentAmount = 50001, gap = 43200`
     * `prevAmount = 30000, currentAmount = 50001, gap = 43201`

2. **`CompliantTransferIsAllowed`** — **HELD**
   * **What it checked:** Ensures the policy grants `TransferAllowed` for a compliant request.
   * **Scope:** Applied to and held across **1 of the 12 states**:
     * `prevAmount = 30000, currentAmount = 20000, gap = 300`

---

### Observations on Property Coverage

* **Narrow positive coverage:** The claim `CompliantTransferIsAllowed` is hardcoded to a single request state (`prevAmount = 30000, currentAmount = 20000, gap = 300`). It does not verify whether compliant transfers are granted in other scenarios (such as when the window expires with `gap = 43201` and `currentAmount = 50000`, or `gap = 43200/43201` with `currentAmount = 20000`).
* **Fixed previous amount:** `prevAmount` was never tested at any value other than `30000`. Behavior with `prevAmount = 0`, values near the cap, or values exceeding the cap was not evaluated.
* **Derived questions omitted:** Automated derived question checks were not run because the policy reads 6 fields, exceeding the tool's default limit of 4 fields. This is an analysis limit, not a policy failure.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 262,899 | 175,366 | 10,475 | 273,374 | 147.3 |
| the review | 1,170 | 0 | 517 | 1,687 | 10.8 |
| the report | 1,243 | 0 | 1,950 | 3,193 | 16.5 |
| **3 model call(s)** | **265,312** | **175,366** | **12,942** | **278,254** | **174.7** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft           155.4s
  preflight         0.0s
  score            23.6s
  review           10.8s
  check             0.0s
  answer           16.5s
  report            0.0s
  total           206.4s
```

Of which 174.7s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
