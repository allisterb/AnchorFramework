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

  4 claims will be checked, over 36 states:
      priorAmount = 20000, currentAmount = 15000, gap = 3600
      priorAmount = 20000, currentAmount = 15000, gap = 43200
      priorAmount = 20000, currentAmount = 15000, gap = 43201
      priorAmount = 20000, currentAmount = 15000, gap = 86400
      priorAmount = 20000, currentAmount = 25000, gap = 3600
      priorAmount = 20000, currentAmount = 25000, gap = 43200
      priorAmount = 20000, currentAmount = 25000, gap = 43201
      priorAmount = 20000, currentAmount = 25000, gap = 86400
      and 28 more

  ExceedingCapWithin12hIsRefused
      says:     whenever gap is at most Window and priorAmount + currentAmount is
                greater than 50000,
                then the policy REFUSES it (TransferAllowed)
      forbids:  gap is at most Window and priorAmount + currentAmount is greater than
                50000,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 12 of the 36 states:
                  priorAmount = 20000, currentAmount = 55000, gap = 3600
                  priorAmount = 20000, currentAmount = 55000, gap = 43200
                  priorAmount = 30000, currentAmount = 25000, gap = 3600
                  priorAmount = 30000, currentAmount = 25000, gap = 43200
                  priorAmount = 30000, currentAmount = 55000, gap = 3600
                  priorAmount = 30000, currentAmount = 55000, gap = 43200
                  and 6 more

  ExceedingCapAfter12hIsRefused
      says:     whenever gap is greater than Window and currentAmount is greater than
                50000,
                then the policy REFUSES it (TransferAllowed)
      forbids:  gap is greater than Window and currentAmount is greater than 50000,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 6 of the 36 states:
                  priorAmount = 20000, currentAmount = 55000, gap = 43201
                  priorAmount = 20000, currentAmount = 55000, gap = 86400
                  priorAmount = 30000, currentAmount = 55000, gap = 43201
                  priorAmount = 30000, currentAmount = 55000, gap = 86400
                  priorAmount = 40000, currentAmount = 55000, gap = 43201
                  priorAmount = 40000, currentAmount = 55000, gap = 86400

  CompliantSessionUnderCapAllowed
      says:     whenever priorAmount is 20000 and currentAmount is 15000 and gap is 1 *
                Hour (= 3600),
                then the policy GRANTS it (TransferAllowed)
      forbids:  priorAmount is 20000 and currentAmount is 15000 and gap is 1 * Hour (=
                3600),
                and yet the policy REFUSES it (TransferAllowed)
      applies:  to 1 of the 36 states:
                  priorAmount = 20000, currentAmount = 15000, gap = 3600

  CompliantSessionAfter12hAllowed
      says:     whenever priorAmount is 30000 and currentAmount is 25000 and gap is
                Window + 1 (= 43201),
                then the policy GRANTS it (TransferAllowed)
      forbids:  priorAmount is 30000 and currentAmount is 25000 and gap is Window + 1 (=
                43201),
                and yet the policy REFUSES it (TransferAllowed)
      applies:  to 1 of the 36 states:
                  priorAmount = 30000, currentAmount = 25000, gap = 43201

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

### Verification Summary: `CumulativeCap.tla` on `agent-policy.dw`

All 4 claims defined in `CumulativeCap.tla` **held** across the **36 concrete states** evaluated by the model checker.

---

### What Was Checked and What Held

The check evaluated combinations of discrete values:
* **`priorAmount`**: `20000`, `30000`, `40000`
* **`currentAmount`**: `15000`, `25000`, `55000`
* **`gap`**: `3600` (1h), `43200` (12h window), `43201` (12h + 1s), `86400` (24h)

Across these 36 states, the following specific claims held:

1. **`ExceedingCapWithin12hIsRefused` (Held across 12 applicable states)**
   * **Rule checked**: When `gap <= 43200` and `priorAmount + currentAmount > 50000`, `TransferAllowed` is refused.
   * **Scope**: Verified for the 12 combinations where amounts exceeded 50,000 within the 12-hour window (e.g., prior 20,000 + current 55,000; prior 30,000 + current 25,000; prior 30,000 + current 55,000; at gaps of 3,600s and 43,200s).

2. **`ExceedingCapAfter12hIsRefused` (Held across 6 applicable states)**
   * **Rule checked**: When `gap > 43200` and `currentAmount > 50000`, `TransferAllowed` is refused.
   * **Scope**: Verified for the 6 combinations where `currentAmount = 55000` with `gap` at 43,201s or 86,400s across prior amounts of 20,000, 30,000, and 40,000.

3. **`CompliantSessionUnderCapAllowed` (Held across 1 applicable state)**
   * **Rule checked**: A session with `priorAmount = 20000`, `currentAmount = 15000`, and `gap = 3600` results in `TransferAllowed` being granted.

4. **`CompliantSessionAfter12hAllowed` (Held across 1 applicable state)**
   * **Rule checked**: A session with `priorAmount = 30000`, `currentAmount = 25000`, and `gap = 43201` results in `TransferAllowed` being granted.

---

### Concrete Bounds and Scope Limitations

* **Exact Value Bounds**: The verification only establishes policy behavior for the **36 discrete states** generated from the specific amounts and gap timestamps listed above.
* **Unchecked States**: This check does not evaluate other transfer amounts (e.g., exact boundary values like 50,000, amounts below 15,000, or intermediate amounts), other time gaps (e.g., gaps between 3,600s and 43,200s, or zero gap), or negative values.
* **Derived Analysis Not Run**: Automated exhaustive property checks were not attempted because `agent-policy.dw` accesses 6 input/output fields, exceeding the default 4-field limit for model space exploration.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 327,388 | 242,859 | 13,097 | 340,485 | 246.4 |
| the review | 1,467 | 0 | 357 | 1,824 | 4.0 |
| the report | 1,629 | 0 | 1,792 | 3,421 | 11.2 |
| **3 model call(s)** | **330,484** | **242,859** | **15,246** | **345,730** | **261.5** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft           254.2s
  preflight         0.0s
  score            17.9s
  review            4.0s
  check             0.0s
  answer           11.2s
  report            0.0s
  total           287.3s
```

Of which 261.5s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
