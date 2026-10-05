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

  2 claims will be checked, over 64 states:
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        1, gap = 60
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        1, gap = 900
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        1, gap = 901
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        1, gap = 1800
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        2, gap = 60
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        2, gap = 900
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        2, gap = 901
      hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1, transferAccount =
        2, gap = 1800
      and 56 more

  CompliantTransferAllowed
      says:     whenever hasVerifyEvent holds and isVerified holds and verifiedAccount
                is 1 and transferAccount is 1 and gap is 60,
                then the policy GRANTS it (TransferAllowed)
      forbids:  hasVerifyEvent holds and isVerified holds and verifiedAccount is 1 and
                transferAccount is 1 and gap is 60,
                and yet the policy REFUSES it (TransferAllowed)
      applies:  to 1 of the 64 states:
                  hasVerifyEvent = TRUE, isVerified = TRUE, verifiedAccount = 1,
                    transferAccount = 1, gap = 60

  UnverifiedTransferRefused
      says:     whenever hasVerifyEvent does not hold or isVerified does not hold or
                verifiedAccount is not transferAccount or gap is greater than 15 *
                Minute (= 900),
                then the policy REFUSES it (TransferAllowed)
      forbids:  hasVerifyEvent does not hold or isVerified does not hold or
                verifiedAccount is not transferAccount or gap is greater than 15 *
                Minute (= 900),
                and yet the policy GRANTS it (TransferAllowed)
      applies:  to 60 of the 64 states:
                  hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1,
                    transferAccount = 1, gap = 60
                  hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1,
                    transferAccount = 1, gap = 900
                  hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1,
                    transferAccount = 1, gap = 901
                  hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1,
                    transferAccount = 1, gap = 1800
                  hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1,
                    transferAccount = 2, gap = 60
                  hasVerifyEvent = FALSE, isVerified = FALSE, verifiedAccount = 1,
                    transferAccount = 2, gap = 900
                  and 54 more

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

### Summary of Results

The property module **`IdentityVerification.tla` held** across all **64 evaluated states**. No counterexamples were found within this tested scope.

---

### Scope and Bounds Checked

The verification ran over a bounded grid of **64 discrete states** formed by combinations of the following values:
* **`hasVerifyEvent`**: `TRUE`, `FALSE`
* **`isVerified`**: `TRUE`, `FALSE`
* **`verifiedAccount`**: `1`, `2`
* **`transferAccount`**: `1`, `2`
* **`gap`**: `60`, `900`, `901`, `1800` (seconds)

Requests involving other account IDs, time intervals outside these four values, or additional context fields were **not checked**.

---

### Claim Breakdown

1. **`CompliantTransferAllowed` — HELD**
   * **Applies to:** Exactly **1 of the 64 states** (`hasVerifyEvent = TRUE`, `isVerified = TRUE`, `verifiedAccount = 1`, `transferAccount = 1`, `gap = 60`).
   * **Result:** The policy permitted `TransferAllowed` for this specific compliant state.

2. **`UnverifiedTransferRefused` — HELD**
   * **Applies to:** **60 of the 64 states** where verification was missing, failed, accounts did not match (1 vs 2), or `gap` was greater than 900 seconds (specifically evaluated at 901 and 1800 seconds).
   * **Result:** The policy refused `TransferAllowed` across all 60 of these states.

---

### Findings Regarding the Properties

* **Gap in Coverage (3 unasserted states):** Out of the 64 states, the two claims only cover 61 ($1 + 60$). There are **3 valid states** that neither claim tests:
  * `verifiedAccount = 1`, `transferAccount = 1`, `gap = 900` (valid 15-minute boundary)
  * `verifiedAccount = 2`, `transferAccount = 2`, `gap = 60`
  * `verifiedAccount = 2`, `transferAccount = 2`, `gap = 900`
* **Overly Specific Positive Test:** `CompliantTransferAllowed` is hardcoded strictly to Account `1` and a `60`-second gap. It does not verify that transfers are allowed for other accounts (like Account `2`) or at other valid time gaps (like `900` seconds).
* **Automated Derived Analysis Skipped:** General automated analysis was not run because the policy reads 6 input/output fields, exceeding the tool's default 4-field threshold.

Every LLM call this run made, with each tool call and its reply, is in `transcript.md` beside this file.

---

*A property module drafted by a model and gated by Anchor. Findings against an agent-authored property module are weaker evidence than findings against one a person wrote.*

## What this run cost

| | tokens in | of which cached | out | total | seconds |
|---|---:|---:|---:|---:|---:|
| draft round 1 | 71,228 | 44,117 | 4,812 | 76,040 | 52.4 |
| the review | 1,075 | 0 | 879 | 1,954 | 7.9 |
| the report | 1,236 | 0 | 1,859 | 3,095 | 13.2 |
| **3 model call(s)** | **73,539** | **44,117** | **7,550** | **81,089** | **73.5** |

Time per stage, model calls and verification together:

```
  describe          0.0s
  draft            60.4s
  preflight         0.0s
  score            20.0s
  review            7.9s
  check             0.0s
  answer           13.2s
  report            0.0s
  total           101.5s
```

Of which 73.5s was model calls; the rest is verification -- TLC runs in `score` and `check`, which cost no tokens.
