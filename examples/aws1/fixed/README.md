# The two findings, fixed and checked

Proposed corrections for the two policies [`../README.md`](../README.md) finds wrong, checked the
same way the originals were found to break: against the same property modules, with every claim
listed in the `.cfg` rather than one. Same file names as the originals, so each diffs against
its counterpart one directory up.

| | the change | checked |
|---|---|---|
| `agent-policy.dw` | the trade gate as **one** `permit`, its two conditions joined with `&&` — AgentCore's own idiom for "both prerequisites", from its [temporal policy examples](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies-temporal.html). Both protections are now required | `TradeGate.tla`, all five claims hold — including `BothIsAllowed`, so the intended path is still open |
| `07-trust-decay.dw` | `unless` turned to `when`, so the trade is permitted only while the advisor has interacted in the last 15 minutes; and `interact_advisor` permitted, which a rule gated on its response needs | `TrustDecay.tla`, both claims that state the article's sentence hold |
| [`agentcore/policies.dw`](agentcore/policies.dw) | both fixes **as AgentCore needs them**: every policy scoped to the gateway, and `eventResource: resource` in every predicate, which AgentCore makes mandatory | parses with `dogwood check-parse`. Not checked by Anchor, which does not yet model AgentCore's event schema; it is the checked text above with the scope and joins put back, which changes nothing when every request goes through one gateway |

```bash
[./]anchor check examples/aws1/fixed --full --no-llm
```

Every rule in both sets is live, both modules hold, no findings: [`findings.md`](findings.md).

**One composition caveat, on the trust-decay fix.** With `when`, policy 7 is right as a standalone
policy, which is how the article publishes it and what `TrustDecay.tla` checks. But it is still a
`permit` on `execute_trade`, so deployed beside the trade gate it becomes a second way in — the
same alternatives effect as finding 2. "Loses access" is a restriction, and in a set a restriction
composes as a `forbid ... unless temporal { formerly within 15m ...interact_advisor::response{ … } }`.
That form is in [`agentcore/policies.dw`](agentcore/policies.dw) as a comment, and is **not**
machine-checked: `TradeGate.tla`'s sessions have no advisor event, so it needs a module stating all
three protections together.

**What this does and does not establish.** Each fix satisfies the claims its module states, within
the bounds the checks report, and parses with the Dogwood binary built from the pinned
`ext/dogwood` submodule. Neither has run in an AgentCore deployment. They are a proposal for the
article, not a tested production policy.

**`TrustDecay10.tla` is not here on purpose.** It asks for a 10-minute deadline, stricter than the
article's sentence sets, and a 15-minute policy is not meant to meet it.
