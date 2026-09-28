---
title: Event schemas and pins
description: Why passing a .dwschema changes what a policy MEANS, not merely what is checked.
---

# Event schemas and pins

A Dogwood policy is evaluated against a history of events. The event schema (`.dwschema`) decides
**which history** — and that changes what the policy means before anything is checked about what it
says.

Always pass `eventSchema` when one exists. It is not an optimisation.

## Pins partition history

A **universal pin** in the schema partitions the event history by one or more fields. Under a pin on
`principal`, a temporal predicate like `formerly within 1h Approve::response` sees only *that
principal's* events — not everyone's.

The consequence is blunt: a rule can be `live` under one reading and `VACUOUS` under the other.

| reading | history a temporal predicate sees |
|---|---|
| **pinned** by `callerPrincipal` — Dogwood's default, and the checker's when no schema is given | only the requesting principal's events |
| **unpinned** (`pinned: false`) | one global trace — every event from every caller |
| **another partition** (a schema's own universal pin, such as `sessionId`) | only the events in its own partition |

**Neither reading is uniformly stricter.** A permit that needs an earlier event fires less often
pinned, because fewer events count. But a forbid that counts earlier events — a rate limit — also
fires less often pinned, so for it the pinned reading is the more permissive one. That is why the
reading belongs in every verdict. When no schema is passed the checker uses Dogwood's default and
says so in its `Reading` field. Do not drop that line when summarising.

A **partial pin** is different: it becomes an ordinary conjunct on the condition rather than a
partition key.

## `max_window` caps how far back a policy may look

The schema also caps the look-back of any `within` clause. **Absent the directive the cap is 24
hours**, so it applies to every policy, schema or not. The bound is inclusive: `within 24h` passes,
`within 7d` does not.

A policy exceeding it is refused, because the gateway's own validator rejects it:

```
error: temporal window `7d` exceeds the maximum allowed window `24h` set by the event
schema's `max_window`
```

Answering questions about such a policy would be answering about something that cannot be deployed.
A schema raises the cap with `max_window = 30d`, or lowers it to tighten what policies may do.

## What to do

- Pass `eventSchema` whenever the policy has one.
- If you do not have one, say in your summary that the answer is under Dogwood's default reading,
  `callerPrincipal` pinned, and that a deployment with a different schema could decide differently.
- If the deployment is known to have no universal pin, pass `pinned: false`.
- Never compare a verdict computed with a schema against one computed without, and call it a change
  in the policy.
