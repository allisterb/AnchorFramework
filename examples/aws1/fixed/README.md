# The two findings, fixed and checked

Proposed corrections for the two policies [`../README.md`](../README.md) finds wrong, checked the
same way the originals were found to break: against the same property modules, with every claim
listed in the `.cfg` rather than one. Same file names as the originals, so each diffs against
its counterpart one directory up.

| | the change | checked |
|---|---|---|
| `agent-policy.dw` | the trade gate: the freshness `permit` grants `execute_trade`, and a `forbid ... unless` refuses it unless this trajectory loaded the profile the trade names. A forbid overrides any permit, so **both** protections are now required | `TradeGate.tla`, all five claims hold -- including `BothIsAllowed`, so the intended path is still open |
| `07-trust-decay.dw` | `unless` turned to `when`, so the trade is permitted only while the advisor has interacted in the last 15 minutes; and `interact_advisor` permitted, which a rule gated on its response needs | `TrustDecay.tla`, both claims that state the article's sentence hold |

```bash
[./]anchor check examples/aws1/fixed --full --no-llm
```

Every rule in both sets is live, both modules hold, no findings: [`findings.md`](findings.md).

**What this does and does not establish.** Each fix satisfies the claims its module states, within
the bounds the checks report, and both parse with the Dogwood binary built from the pinned
`ext/dogwood` submodule. Neither has run in an AgentCore deployment, and the transcription notes in
`../agent-policy.dw` still apply: resource scopes and `eventResource` joins are dropped. They are a
proposal for the article, not a tested production policy.

**`TrustDecay10.tla` is not here on purpose.** It asks for a 10-minute deadline, stricter than the
article's sentence sets, and a 15-minute policy is not meant to meet it.
