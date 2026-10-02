---
title: The modelled subset, and why a refusal is not a failure
description: What Anchor will and will not translate, and why it refuses rather than approximating.
---

# The modelled subset

Anchor translates Dogwood policy text into TLA+ records that a validated evaluator checks. It
models a **subset** of the language. When a policy uses something outside it, the checker refuses:

```
REFUSED: like_impossible.dw is outside the modelled subset
  input.stock is constrained by 2 `like` patterns at once and no value satisfying all of
  them could be constructed; deciding that needs glob intersection, which is not modelled
```

**A refusal is a deliberate answer, not a breakdown.** The alternative — translating approximately
and reporting a verdict anyway — produces a verdict nobody can attribute: you could not tell whether
`VACUOUS` described the policy or the approximation. So the house rule is to refuse rather than
approximate, and refusals name the construct so they are actionable.

`Answered: false` with an empty finding list therefore means **no verdict was produced**. It does
not mean "no problems found". Never summarise it as a clean result.

## What is modelled

- `permit` / `forbid`, with forbid-overriding-permit and default-deny
- action sets and scope binds, including wildcard (`_`) and fresh variables
- Cedar-level conditions: comparison, `&&`, `||`, `!`, parentheses
- temporal terms: `formerly within <duration>`, aggregates, `exists` with an entity-typed binder
- `like` patterns (glob), `ip()` and `isInRange` over IPv4, decimals, macros
- event schemas: universal and partial pins, `max_window`

## Common reasons for a refusal

| refusal | why |
|---|---|
| window exceeds `max_window` | the gateway's validator would reject the policy — see `event-schemas-and-pins` |
| two `like` patterns on one field with no constructible joint witness | deciding it needs glob intersection |
| ordering compared against a non-integer | ordering is modelled for **integers only**; the engine denies on decimals |
| IPv6 address | not modelled |
| more than `maxFields` input/output fields | the request space is the product of their domains, so it would explode |
| event kinds outside AgentCore's convention | the model only knows `request` / `response` / `error` |
| mixed value kinds on one field | scalars are tagged, and a cross-kind comparison is refused rather than silently answered |

## What to do with a refusal

Read the reason — it names the construct. Then either simplify the policy to stay inside the subset,
or tell the user plainly that this policy cannot be checked and which construct is responsible. Do
not retry the same call, and do not fall back to reasoning about the policy yourself and presenting
it as a checked result.

## What is NOT modelled, and which of it is deliberate

Measured against Dogwood's own grammar, with each construct confirmed legal by
`dogwood check-parse` before being called a gap:

| construct | example | |
|---|---|---|
| **a temporal operator where an ATOM is expected** | `formerly within 1h A since within 1h B`, `!formerly within 15m A`, `formerly within 2h (A && formerly within 30m B)` | **not modelled.** A `since`'s left operand, a bare `!`'s operand and a `formerly` body are *atoms* — a predicate, or a parenthesised Cedar-level condition — and another temporal operator cannot nest there. Measured cost of the gap: **2 of 620** policy files in Dogwood's own regression corpus, **0 of 94** docs examples, **0 of 7** in AWS's temporal-policies article |
| **information providers** | `BedrockGuardrails::SensitiveInformation(…)`, `Strings::Matches(…)` | not modelled, and **refusing is the correct answer** rather than a gap: a provider is a sandboxed Rhai script, so the decision is not a function of the policy and the trace at all. Nothing a model checker could say about it would be true |
| other `context.system` fields | `context.system.now` compared as a datetime | only `.toTime()` is modelled — the time of day. A datetime comparison needs calendar arithmetic |
| an aggregate compared against an aggregate | `(count …) < (count …)` | not modelled — an aggregate's bound must be an integer literal |
| entity attributes | `principal.dept` | deliberate: Anchor models actions, event kinds and input/output fields, not entity hierarchies |
| a scope naming an entity | `resource == AgentCore::Gateway::"arn:…"`, `principal == User::"alice"` | **not yet modelled — a gap, because AgentCore's examples scope every policy to its gateway.** Refused rather than dropped: `principal` and `resource` are modelled only as the caller of each event — what pins and `callerPrincipal` / `callerResource` binds correlate on — not as which entity it is, and dropping the scope would widen the policy to every entity. When every request goes through one gateway, removing the scope by hand is safe; say so in the file |
| AgentCore's event fields | `eventResource: resource`, `eventPrincipal: principal` | **not yet modelled — a gap, because AgentCore makes `eventResource: resource` mandatory in every temporal predicate.** AgentCore's events name their scope fields `eventPrincipal` / `eventResource`; Dogwood's default event schema names them `callerPrincipal` / `callerResource`, which is all Anchor models, and an event schema declaring other fields is refused. So a policy written for AgentCore must have its joins removed by hand — safe with one gateway — before Anchor will check it. The open-source `dogwood validate` rejects these fields too, under its default schema |
| array terms | `input.tags: [1, 2]` | not modelled |
| disjunction between temporal terms | `formerly … \|\| formerly …` | deliberate |

Everything else in the temporal grammar is modelled, including the parts easiest to assume are
not: **`since`** with full MFOTL semantics and a negated left operand (`!A since within W B`),
**aggregates** (`count`, `sum`, `for` binders, `tp()`, the `exists` idiom), field injection,
`previous`, dotted field paths, entity and decimal terms, wildcards, negative integers and macros.

## The wall clock

`context.system.now.toTime()` — the time of day at the moment of the decision, which is what a
"business hours only" rule is written against — is modelled, together with Cedar's `duration(…)`
literal:

```
when { context.system.now.toTime() >= duration("9h")
    && context.system.now.toTime() <= duration("17h") }
```

It is **not determined by the trace**: it is a value the request carries and the policy reads. So
it is modelled as a request field, and gets a field's domain — the values the policy names plus
ones either side — which is what makes both "inside the window" and "outside" reachable. A window
written backwards (`>= 17h && <= 9h`) is therefore reported **VACUOUS**, correctly: no time of day
satisfies it.

Cedar counts a duration in **milliseconds** and so does the model, so `duration("9h")` is
32400000. Only `.toTime()` is modelled; `now` compared as a datetime would need calendar
arithmetic and is refused.

## Is it even a Dogwood policy?

This subset is read by Anchor's own parser, which means a refusal has two possible meanings under
one message: *the construct is outside the subset*, or *the policy is broken*. Those need opposite
responses, and our parser cannot tell them apart — it is the thing whose coverage is in question.

The reference implementation settles it, and `--syntax` (`syntax` on `CheckPolicy`) asks it first:

```
SYNTAX ERROR in policy.dw -- the reference implementation will not parse it.
Nothing below was checked.

× unexpected token `{`, expected comparison operator
   ╭─[4:9]
 5 │ │               AgentCore::Action::"execute_buy"{
   · ╰──── unexpected token `{`, expected comparison operator
```

**A syntax error is not a verification finding** and must never be reported as one — the policy has
not been checked, and the exit code is 2 (no verdict), never 0. When a refusal happens the engine is
consulted anyway, so a broken file is never left looking like a limitation of this tool; pass the
flag when you want the check to come *first*, on a policy somebody has just edited.

## Three limits worth knowing separately

- **Integers only for ordering.** `>`, `<`, `>=`, `<=` are modelled for integers. Decimals are
  excluded deliberately, because the reference engine denies on them.
- **Addresses are four octets, never a 32-bit number.** TLC works in Java ints, so an address above
  127.255.255.255 is not a value it can hold as an integer.
- **An integer literal has to fit in ±2,147,483,646.** TLA+ integers are unbounded; this is *TLC's*
  limit, and the number is odd rather than a power of two because TLC reserves `Integer.MAX_VALUE`
  (2147483646 checks, 2147483647 does not). Cedar's `Long` runs to 2^63-1, so a budget cap written
  in cents is a valid policy this checker cannot represent — refused by name, because unrefused it
  surfaces as `Error: TLC can't handle a number this big.` from inside a run that names neither the
  policy nor the field. **Scaling the units makes the same comparison fit.**
