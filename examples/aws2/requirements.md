# Requirements — the same five, against the policy set as deployed

Each heading below is one requirement from
[the AWS article](https://aws.amazon.com/blogs/machine-learning/authoring-dogwood-policies-from-natural-language-in-amazon-bedrock-agentcore/),
quoted verbatim, and each is checked against **`agent-policy.dw`** — all five rules together, with
the supporting reads permitted.

## Why not the individual files

[`intents.md`](intents.md) sweeps them one per file, and for three of them that cannot work.
`03-cumulative-cap.dw`, `04-refund-rate-limit.dw` and `06-supervisor-approval.dw` contain a
**`forbid` and nothing else**. Cedar is default-deny, so on its own such a file grants nothing at
all — and any claim of the form *"this request is allowed"* fails whatever the rule says. The first
sweep produced exactly that: a violated `FirstRefundForAccountAllowed` against a policy that is
correct.

A `forbid` is only meaningful beside the `permit` it carves an exception out of, which is what
`agent-policy.dw` is and how these would be deployed. Same requirements, same prose, a context in
which they can be true or false.

```bash
anchor auto examples/aws2/agent-policy.dw --intents examples/aws2/requirements.md --max-fields 8
```

One property module per requirement, named from its heading, in `anchor/<heading>/`.

## business-hours

> Refunds might be issued only during business hours, defined as 9:00 AM-5:00 PM UTC, and only for
> amounts of $2,500 or less.

## identity-verification

> Do not initiate a transfer unless the caller's identity has been verified for that same account
> within the previous 15 minutes.

## cumulative-cap

> Block a transfer if the total amount transferred in the past 12 hours would exceed $50,000.

## refund-rate-limit

> The agent might attempt no more than three refunds against the same account within one hour.

## supervisor-approval

> A refund over $500 requires a supervisor approval for that charge within the previous 30 minutes.
