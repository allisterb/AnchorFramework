# agent-policy.dw

**Stated intention.** Do not initiate a transfer unless the caller's identity has been verified for that same account within the previous 15 minutes.

## What was checked

`IdentityVerification.tla`, drafted from the intention above and kept because it caught 1 broken version(s) of this policy.

### Does it say what you asked for?

A second model, shown only the requirement and the plain-English reading of the claim — never the formal claim itself — judged that they match. That is an agreement between two models, not a proof that the claim captures the requirement.

## Verdicts

```
Policy set: agent-policy.dw
Property module: IdentityVerification.tla

The property module HOLDS: every claim in it holds.

WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the states it ranges over its condition applies to:

IdentityVerification

  Every value each variable takes -- nothing else is checked:
      hasVerification  FALSE, TRUE
      vAccount         1, 2
      tAccount         1, 2
      verified         FALSE, TRUE
      gap              60, 900, 901, 1800

  5 claims will be checked, over 64 states:
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE, gap = 60
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE, gap = 900
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE, gap = 901
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE, gap = 1800
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = TRUE, gap = 60
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = TRUE, gap = 900
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = TRUE, gap = 901
      hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = TRUE, gap = 1800
      and 56 more

  CompliantTransferIsAllowed
      says:     whenever hasVerification holds and verified holds and vAccount is 1 and
                tAccount is 1 and gap is 60,
                then the policy GRANTS it (TransferAllowed)
      forbids:  hasVerification holds and verified holds and vAccount is 1 and tAccount
                is 1 and gap is 60,
                and yet the policy REFUSES it (TransferAllowed)
      applies:  to 1 of the 64 states:
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = TRUE,
                    gap = 60

  NoVerificationIsRefused
      says:     whenever hasVerification does not hold,
                then the policy REFUSES it (TransferAllowed)
      forbids:  hasVerification does not hold,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 32 of the 64 states:
                  hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 60
                  hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 900
                  hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 901
                  hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 1800
                  hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = TRUE,
                    gap = 60
                  hasVerification = FALSE, vAccount = 1, tAccount = 1, verified = TRUE,
                    gap = 900
                  and 26 more

  FailedVerificationIsRefused
      says:     whenever hasVerification holds and verified does not hold,
                then the policy REFUSES it (TransferAllowed)
      forbids:  hasVerification holds and verified does not hold,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 16 of the 64 states:
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 60
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 900
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 901
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 1800
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 60
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 900
                  and 10 more

  MismatchedAccountIsRefused
      says:     whenever hasVerification holds and vAccount is not tAccount,
                then the policy REFUSES it (TransferAllowed)
      forbids:  hasVerification holds and vAccount is not tAccount,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 16 of the 64 states:
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 60
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 900
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 901
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 1800
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = TRUE,
                    gap = 60
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = TRUE,
                    gap = 900
                  and 10 more

  ExpiredVerificationIsRefused
      says:     whenever hasVerification holds and gap is greater than FifteenMinutes,
                then the policy REFUSES it (TransferAllowed)
      forbids:  hasVerification holds and gap is greater than FifteenMinutes,
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 16 of the 64 states:
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 901
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = FALSE,
                    gap = 1800
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = TRUE,
                    gap = 901
                  hasVerification = TRUE, vAccount = 1, tAccount = 1, verified = TRUE,
                    gap = 1800
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 901
                  hasVerification = TRUE, vAccount = 1, tAccount = 2, verified = FALSE,
                    gap = 1800
                  and 10 more

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
anchor check examples\aws2\agent-policy.dw --full --property examples\aws2\anchor\identity-verification\IdentityVerification.tla
```

## Reported

### Verification Summary

All 5 claims in `IdentityVerification.tla` **held** across the **64 states** evaluated for `agent-policy.dw`. No counterexamples were found within these bounds.

---

### What Was Checked (The Exact Bounds)

The verification tested combinations of only the following variable values (a total of $2 \times 2 \times 2 \times 2 \times 4 = 64$ states):

*   **`hasVerification`**: `FALSE`, `TRUE`
*   **`vAccount`**: `1`, `2`
*   **`tAccount`**: `1`, `2`
*   **`verified`**: `FALSE`, `TRUE`
*   **`gap`**: `60`, `900`, `901`, `1800` (representing elapsed seconds)

**What was not checked:**
*   Any account identifiers other than `1` and `2`.
*   Any time gap values other than `60`, `900`, `901`, and `1800`.
*   Derived/automated exploratory properties were **not run** because the policy reads 6 fields, exceeding the tool's 4-field automated exploration threshold.

---

### Claim-by-Claim Results

1.  **`CompliantTransferIsAllowed`** — **HELD**
    *   **Rule:** Grants `TransferAllowed` when verification exists, `verified` is true, accounts match on `1`, and `gap` is `60`.
    *   **Scope:** Evaluated on **1 state** out of 64.
    *   **Finding on the property:** This claim only checks a single specific scenario (account `1` with a `60`-second gap). It does not test whether compliant transfers succeed for account `2`, nor does it check whether a `gap` of `900` seconds is permitted.

2.  **`NoVerificationIsRefused`** — **HELD**
    *   **Rule:** Refuses `TransferAllowed` whenever `hasVerification` is `FALSE`.
    *   **Scope:** Evaluated across **32 states** where `hasVerification` is `FALSE`.

3.  **`FailedVerificationIsRefused`** — **HELD**
    *   **Rule:** Refuses `TransferAllowed` whenever `hasVerification` is `TRUE` but `verified` is `FALSE`.
    *   **Scope:** Evaluated across **16 states** where `hasVerification` is `TRUE` and `verified` is `FALSE`.

4.  **`MismatchedAccountIsRefused`** — **HELD**
    *   **Rule:** Refuses `TransferAllowed` whenever `hasVerification` is `TRUE` and `vAccount` does not equal `tAccount` (i.e., `vAccount = 1, tAccount = 2` or `vAccount = 2, tAccount = 1`).
    *   **Scope:** Evaluated across **16 states**.

5.  **`ExpiredVerificationIsRefused`** — **HELD**
    *   **Rule:** Refuses `TransferAllowed` whenever `hasVerification` is `TRUE` and `gap` exceeds 15 minutes (tested at `901` and `1800` seconds).
    *   **Scope:** Evaluated across **16 states**.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 118,406 | 68,075 | 6,366 | 124,772 | 81.6 |
| the review | 1,955 | 0 | 294 | 2,249 | 3.7 |
| the report | 2,027 | 0 | 1,961 | 3,988 | 14.2 |
| **3 model call(s)** | **122,388** | **68,075** | **8,621** | **131,009** | **99.5** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft            92.5s
  preflight         0.0s
  score            40.5s
  review            3.7s
  check             0.0s
  answer           14.2s
  report            0.0s
  total           150.9s
```

Of which 99.5s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
