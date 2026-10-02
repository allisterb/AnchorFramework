---
title: Decision tables
description: Checking a policy against what was meant, without writing TLA+ — the table format, where a table must come from, and how to read the result.
---

# Decision tables

`CheckDecisionTable` checks a policy set against a **decision table**: sessions of requests, each
with the ALLOW or DENY it should get. Every decision is put to Anchor's model **and** to the Dogwood
engine, and the result lists each one with what the table expected, what each of the two decided, and
which rules decided it.

## Why a table

A policy that validates is legal, not correct. `dogwood validate` checks syntax and types; it cannot
know what the policy was for. Reading a policy back into English and agreeing with the reading
checks nothing either, because the reading was made from the policy.

A table is the cheapest statement of intent there is. A person can write or approve one without
reading Dogwood, and it is exact where prose is not. AWS's own temporal-policy posts print tables
beside their policies: checked against them, the policies of one post did the opposite of their own
table on 16 decisions (`examples/aws1`).

## Where the table must come from

**From the requirement, never from the policy.** A table derived from the policy's text restates the
policy and agrees with it whatever it says. If you drafted the policy, ask the person for the table,
or write it from their words and have them approve it *before* checking.

**Include the rows that should be DENIED.** Most mistakes in a policy are things it allows: a cap
written as a `permit` grants from an empty session; two `permit`s on one action are alternatives,
not requirements. A table of only ALLOW rows cannot see either.

Two questions are worth a row each, because the prose rarely settles them and the policy always does:

- **The attempt or the outcome?** A denied request is still recorded. A cap that sums `::request`
  counts refused attempts; one gated on `::response` needs the call to have succeeded.
- **One session, or across sessions?** On AgentCore, history is kept per session, and the caller
  chooses the session ID. A cap meant per customer is per session unless a row says otherwise. Use
  `session=s2` to put a request in a second session.

## The format

One line each. Lines may carry a `//|` prefix, so a table can live in a `.dw` file's comments.

```
target FinTarget
row table: approval, then a large trade, then a second one
@0   request  approve_trade   { status: "approved" }  ALLOW
@1   response approve_trade   { status: "approved" } -> { }
@10  request  execute_trade   { cost: 30000 }  ALLOW
@11  response execute_trade   { cost: 30000 } -> { }
@20  request  execute_trade   { cost: 30000 }  DENY
@30  session=s2 request execute_trade { cost: 30000 }  DENY
```

- **Times are seconds.** Windows are closed: an event exactly `W` back is inside `within W`.
- **A request carries its expected decision.** A `response` (the call completed) or an `error` (the
  request was denied, or the tool failed) is history and carries none.
- **A response may only follow a request the table says is ALLOWED.** A table that breaks this
  describes a history the gateway could not record, and is refused as **malformed**, not checked.
- `row <source>: …` names where the expectation came from (`table`, `prose`, `ours`: any word). A
  line may name its own source after its verdict.
- `target T` prefixes tool names with `T___`, AgentCore's naming for an MCP target's tools.
- `finding` after a verdict marks a decision the policy is **known** to decide the other way, for
  keeping a known defect checked: should the policy ever start doing what the table says there, the
  run reports it.

## Reading the result

| field | means |
|---|---|
| `reading` | the event schema the verdicts were reached under. **Report it**: the same table can pass under one and fail under another |
| `agrees: false` | **a finding about the policy.** Report the row, the expected verdict, the policy's, and the rules |
| `modelRules`, `engineRules` | which rules decided it, 1-based in file order. The right verdict through the wrong rule is still worth knowing |
| `modelVersusEngine: true` | Anchor and the engine disagree **with each other**. A defect in Anchor, not a finding about the policy, and must be reported as one |
| `malformed` | the table could not have been recorded; nothing was checked |
| `rejectedByAgentCore` | AgentCore would refuse to create the policy as written; nothing was checked |

When the Dogwood binary is not built, only the model answers, and `engine.ran` says so. The engine is
the stronger half; say which you had.

## What a pass establishes

That the policy decides **these** sessions as the table says, under this reading. Nothing about
sessions the table does not contain. A table is evidence of exactly its rows, so add the rows the
requirement cares most about, the denials above all. Then use `CheckPolicy` for the questions a table
cannot ask: whether any rule is inert, and whether an edit made the policy more permissive.
