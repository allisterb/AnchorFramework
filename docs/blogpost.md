# Agents for Humans: When an Agent Policy Passes Every Check and Is Still Wrong

There is a class of bug that no test suite will find, because the code is correct. It does exactly
what it says. What it says is not what anyone meant.

I built **Anchor** for the Agents for Humans hackathon to find that class of bug in the policies
that govern AI agents — and the thing I did not expect was how much of the work went into stopping
my own agent from cheerfully telling me everything was fine.

## The problem

AWS shipped **Dogwood** last year: a policy language for controlling what an AI agent is allowed to
do, built into Amazon Bedrock AgentCore. It extends Cedar with *time*. Where Cedar decides one
request in isolation, Dogwood decides it against a history — *has an approval already happened*,
*how much has been spent in the last twelve hours*, *how many refunds has this session attempted*.

That is exactly the right shape for governing an agent, because an agent's danger is rarely one
action. It is a sequence of individually reasonable actions.

It is also exactly the shape that is hard to get right. Here is a rule from an AWS blog post,
paraphrasing its own stated requirement:

> Block a transfer if the total amount **transferred** in the past 12 hours would exceed $50,000.

The policy implementing it sums `::request` events. Under AgentCore's convention a request is
recorded whether or not it succeeded. So a **refused** $60,000 transfer — one that moved no money at
all — spends the entire budget, and blocks every legitimate transfer for the next twelve hours.

The policy parses. It type-checks. It validates against its schema. Every rule in it is live —
none is dead, none is redundant, none can never fire. It is a perfectly healthy policy that does
the wrong thing, and the only way to know is for somebody to have written down what it was *for*.

## What Anchor does

Anchor translates a Dogwood policy mechanically into **TLA+**, Leslie Lamport's specification
language, and puts questions to the **TLC** model checker. It works in four escalating modes.

The first needs nothing from you and answers three questions per rule, each with a concrete witness
session or a bounded no: *can this permit ever grant anything*, *is this rule doing anything at all*,
and *do two versions of a policy decide differently*. That catches dead controls — a `forbid` that
denies nothing because nothing was ever going to be allowed. It reads like a control and is not one.

The second needs you to say what the policy was for, as a **property module**: a formal statement of
intent, checked against the policy. That is what finds the transfer bug above. It is also the mode
with a barrier — most people who need this cannot write TLA+.

So the last two modes have an agent write it. **`auto`** takes a sentence of prose and drafts the
property module. **`hitl`** does the same with a person answering when something goes wrong — never
about TLA+, always about the requirement.

## How it is built

The agent half is a **Strands Agents SDK `Graph`**, and the SDK is doing real structural work rather
than being a convenient way to call a model in a loop.

```
describe -> draft -> preflight -> score -> review -> [confirm] -> check -> answer -> report
```

Three of those nodes are language models. The rest are ordinary Python presenting the same
interface, so the graph is uniform while the criteria stay in code where nothing can negotiate with
them.

The most important line in the whole project is one I did not write — it is a constraint
`GraphBuilder` enforces: **one `Agent` instance cannot be two nodes.** The agent that *drafts* a
property is structurally incapable of being the agent that *reports* on it, and neither sees the
other's context. That matters because the best-documented failure in agentic formal verification is
that a model asked to produce both an artifact and its specification discovers that a trivial
specification is the cheapest way to pass.

There is one more separation that is easy to miss: **the drafting model is not given the policy's
rule conditions.** It gets a vocabulary generated mechanically from the policy, a knowledge article
on writing property modules, and your prose. That is deliberate — a property derived from a policy
is a restatement of that policy and will always pass. Only a property derived from a *requirement*
can disagree with the rules, and disagreeing is the entire point. The separation is not airtight:
its `evaluate` tool can read the generated rule set, and it is told, rather than prevented, to
decide its claims from the requirement first.

Underneath, the checker runs TLC out of process on a real JVM, and the real **Dogwood** binary is
kept in the loop as a second opinion: when a claim breaks, the counterexample is carried back to the
reference engine as an event trace, so the verdict printed beside the finding is *the engine's*,
not ours.

## The challenge: a gate that caught nothing

Every one of those gates exists because an agent will otherwise hand you a specification that is
true and empty. The strongest of them is **mutation scoring**: break the policy on purpose —
delete rules, invert effects, drop conditions — and re-check. A property that still holds of a
policy with its protections removed constrains nothing, whatever it looks like.

I built it, it ran, drafts passed it, and I believed it.

Then I measured it. On a seven-rule policy, the gate caught **0 of 8** mutants. Raising the cap to
21 caught **4**.

The bug was in one line. Mutants were generated grouped by rule — every mutation of rule 1, then
every mutation of rule 2 — and the cap took a *prefix* of that list. So `--mutants 8` on a seven-rule
policy exhaustively broke rules one, two, and part of three, and never touched rules four through
seven. A property about rule six was scored against a policy whose rule six was pristine. It passed,
correctly, having tested nothing.

The fix is trivial — take the mutants breadth-first, one per rule, round-robin — and the lesson is
not. **A gate that reports success while testing the wrong thing is worse than no gate**, because it
manufactures confidence. The whole project exists to say that a policy can look healthy and be
wrong; it turned out my defence against that could look healthy and be wrong in precisely the same
way. The only thing that caught it was refusing to accept "the gate passed" as evidence and asking
what it had actually broken.

That is now the habit the codebase is built around. `VACUOUS` is falsification-tested rather than
observed. Every report states its bound. Every report says whether the property was written by a
person or drafted by a model, because those are not equally good evidence.

## Does it work?

I ran `auto` unattended against the five requirements of that AWS article, taken verbatim. It
accepted **one of five**.

That number is the honest headline. Every one of the four failures was a *well-formed* property that
said something the brief did not quite mean — which is the user-intent formalization gap, measured
instead of asserted, and the reason the human-in-the-loop mode exists at all. Two of the four have
since been closed by `hitl`, where a person answered one question about the requirement and the
next draft held.

## Try it

Everything ships in one container — .NET, a JVM, CPython and the Rust reference engine:

```bash
docker pull allisterb/anchor:latest
docker run --rm -w /app allisterb/anchor:latest \
    check examples/aws2/agent-policy.dw --property examples/aws2/CumulativeCap.tla --max-fields 8
```

Twelve seconds, no API key, and it reports the refused-transfer bug with the request that proves it.

Source: [github.com/allisterb/Anchor](https://github.com/allisterb/Anchor)

---

*Anchor is Apache 2.0. Built with the Strands Agents SDK; the agent also deploys to Amazon Bedrock
AgentCore as a container serving `POST /invocations`.*
