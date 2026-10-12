# Specs

Models of agent workflows, one directory per subject. `SpecTests` in `tests/Anchor.Tests.Verifier`
runs every one of them on each build — TLC over the TLA+, Dafny over the `.dfy` — so a spec that
stops verifying, or a bug variant that stops being caught, fails the suite.

**Every directory has its own README** with the detail; this page is the map and the cross-cutting
argument. [`strands/DependencyDAG/README.md`](strands/DependencyDAG/README.md) additionally carries
a TLA+ notation primer for readers new to the language, and the full account of how a Strands agent
graph is translated into a model.

The three groups answer different questions, and **no spec depends on one in another group** — every
`EXTENDS` and `INSTANCE` resolves inside its own directory.

### `policy/` — what an authorization decision means

Models of the policy languages an agent's tool calls are authorized against. Both are validated
against a real engine rather than only against their documentation.

| | |
|---|---|
| [`cedar/`](policy/cedar/README.md) | a differential test between a TLA+ model of Cedar and the real engine. |
| [`TemporalPolicy/`](policy/TemporalPolicy/README.md) | session-aware (Dogwood) policies, and three questions about any `.dw` file: can this permit ever grant anything, does this rule matter, and did this edit change a decision? Catches a permit killed by an unrelated rule elsewhere in the set, and a gate that opens on refused attempts. Its semantics are differential-tested against Dogwood's own corpus. |

**The split between the two groups is deliberate and the seam is worth naming.** `policy/cedar`
asks whether a policy *says* what its author meant; `strands/ToolExecutor` asks whether the thing
*enforcing* it does what the policy assumes. A policy analyser cannot see the second, by
construction. Both have to hold, and they fail independently.

### `strands/` — what the SDK actually does

Models of Strands' own behaviour, each tied to code in the SDK rather than to its documentation.

| | |
|---|---|
| [`DependencyDAG/`](strands/DependencyDAG/README.md) | several tasks in outline: HP10 from arXiv:2510.14133 Table 1. The target of the Strands graph translator. |
| [`StrandsGraph/`](strands/StrandsGraph/README.md) | the Strands executor **as it actually runs** — batch, await, recompute readiness, fail fast, stop. Catches a workflow that reports success having skipped a node. |
| [`ToolExecutor/`](strands/ToolExecutor/README.md) | the `before_tool_call` hook under concurrent tool execution — a rate limit that holds only because a synchronous callback has no suspension point. |

### `foundations/` — properties any agent has

Neither Strands-specific nor policy-specific: budgets, termination, retry, and the task lifecycle.
These came first and are what the rest is built on.

| | |
|---|---|
| [`BoundedRetry/`](foundations/BoundedRetry/README.md) | one agent, one budget. Modelled in TLA+ **and** implemented in Dafny, so the two tools can be compared on the same problem. Crosses into real Python. |
| [`SharedBudget/`](foundations/SharedBudget/README.md) | several agents, one budget. TLA+ only — the fault is in the interleaving, which Dafny cannot express. |
| [`TaskLifecycle/`](foundations/TaskLifecycle/README.md) | one sub-task in full: the eleven-state lifecycle from arXiv:2510.14133 Table 2, checked. |

**One thing not to undo:** `strands/DependencyDAG/` and `strands/StrandsGraph/` each contain a
**generated** `Workflow.tla`, with the same module name and different contents. They coexist only
because TLC resolves modules per-directory. Never flatten those two together.

Each directory pairs a spec that verifies with variants that carry one deliberate mistake each. The
variants are the load-bearing half: a verifier that only ever reports success proves nothing, so
these pin down that a specific mistake is caught and which property catches it.

| `BoundedRetry/` | |
|---|---|
| `BoundedRetry.tla` | an agent attempting a task against a model that may never succeed. Verifies. |
| `Bug1_Overshoot.tla` | with a wrong affordability check. Violates `BudgetSafe`. |
| `Bug2_FreeRetry.tla` | with an uncharged retry path. Violates `EventuallyTerminates`. |

| `BoundedRetry/` (Dafny) | |
|---|---|
| `BoundedRetry.dfy` | the same state machine, executable. Verifies. |
| `BoundedRetryFreeRetry.dfy` | the same uncharged retry path. Fails `decreases`. |
| `BoundedRetryExtern.dfy` | the model bound to real Python via `{:extern}`. Verifies, translates, runs. |
| `anchor_model.py` | the Python behind that boundary — the one thing the proof asks of the outside world. |

| `SharedBudget/` (TLA+ only) | |
|---|---|
| `SharedBudget.tla` | several agents, one budget, atomic acquire. Verifies. |
| `Bug3_CheckThenReserve.tla` | check and reserve as two steps. Violates `BudgetSafe`. |

| `TaskLifecycle/` | |
|---|---|
| `TaskLifecycle.tla` | the per-subtask lifecycle from arXiv:2510.14133 Table 2. Twelve properties, all hold. |
| `TaskLifecycle_TL4Published.cfg` | TL4 exactly as published. **Expected to fail** — see below. |
| `Bug4_UnboundedRetry.tla` | the same, with the retry budget removed. TL1 fails as a lasso. |

| `DependencyDAG/` | |
|---|---|
| `DependencyDAG.tla` | four tasks in a DAG. HP10 holds, and so does termination. |
| `Bug5_NoFailurePropagation.tla` | the same without orphan cancellation. HP10 **still holds**; the graph never finishes. |
| `Workflow.tla` | the graph itself, separated out so it can be replaced by a generated one. |
| `anchor_conditions.py` | Strands edge conditions that carry their own TLA+ meaning. |

| `StrandsGraph/` | |
|---|---|
| `StrandsGraph.tla` | the executor loop: batch, await, recompute readiness, fail fast, stop. Verifies on the guarded workflow. |
| `Workflow.tla` | the graph, shared in form with `DependencyDAG` and generated the same way. |

The workflow-shaped counterexamples live in `tests/strands/graph_to_tla.py`, which checks one graph
against **both** models and prints what the SDK actually did beside them. They disagree in both
directions, and neither is a refinement of the other.

| `TemporalPolicy/` | |
|---|---|
| ***In use*** | ***what `anchor check`, the MCP server and the drafting agent run on*** |
| `DogwoodSemantics.tla` | the evaluator: our reading of Dogwood's temporal operators — `formerly`, `previous`, `since`, the `count`/`sum` aggregations, and the partitioning an event schema's `pin` imposes. Differential-tested against Dogwood's own corpus on 911 pairs. |
| `Vacuity.tla` | **the session model the checker runs** — any parsed `.dw`, any rule. Compares two policy sets across every session: the full set against itself-minus-a-rule (does the rule matter?) or against a second file (did the edit change anything?), and asks whether each permit ever grants. Its questions are **meant to fail**: a violation is the witness. Runs on the `PolicyUnderTest.tla` that `src/checker/properties.py` generates from the `.dw`. |
| ***Current, standalone*** | ***the session-rotation finding: uses `DogwoodSemantics`, run by the spec tests, not by any Anchor command*** |
| `SessionRotation.tla` | a caller who controls the session id. Rotation defeats an aggregate cap and cannot touch an approval gate — the two shapes fail in opposite directions. |
| `rotation_aggregate.dw`, `rotation_approval.dw` | the policies, as **real Dogwood text**. |
| `RotationPolicies.tla` | generated from those by `src/translator/dw_to_tla.py`, using the parser validated against Dogwood's corpus. The suite fails if it drifts from the `.dw` sources. |
| `SessionRotation.cfg` | aggregate cap, rotation allowed. **Cap violated** in three steps. |
| `NoRotation_CapHolds.cfg` | the control: same policy, rotation disabled. Cap holds — which also proves the aggregate is live. |
| `Rotation_ApprovalGateHolds.cfg` | approval gate, rotation allowed. Gate holds. |
| ***The original prototype*** | ***no longer used by any Anchor command, superseded by `Vacuity.tla` + `DogwoodSemantics.tla`; kept because the spec tests run it*** |
| `TemporalPolicy.tla` | the first session model, with its own evaluator (`PermitFires`) where `Vacuity.tla` uses `DogwoodSemantics`. Checks `NeverFires` only. |
| `Policies.tla` | the hand-written schema and policy set it runs on. Nothing else uses it. |
| `TemporalPolicy.cfg` | approvals permitted, gate on `::response`. Satisfiable. |
| `Vacuous_ForbiddenApproval.cfg` | approvals forbidden. **Vacuous** — a permit killed by an unrelated rule. |
| `RequestGated_SurvivesForbid.cfg` | same forbid, gate on `::request`. Satisfiable, **and that is the bad news**. |

## BoundedRetry

**The model is deliberately not specified.** It appears only as nondeterminism: an attempt costs
anything in `1..MaxCost`, and returns success or failure by arbitrary choice. Every property has to
hold for all of those behaviours, including an adversarial model that never once succeeds and
charges the maximum every time. That follows from LLM non-determinism being a hardware-level
reality rather than something a prompt can fix — you cannot verify the model, so you verify the
harness under a model permitted to behave as badly as it likes.

Two design decisions carry the safety proof:

- **Affordability is checked against the worst case**, `spent + MaxCost <= Budget`, not against the
  expected cost. The real cost is unknown until the attempt returns.
- **The cost is reserved before the call, not charged after it.** `BudgetSafe` counts
  `spent + reserved`, which is what makes it hold across the window where a call is out and its cost
  is not yet known.

`EventuallyTerminates` is the more interesting property: the task ends *whatever the model does*,
because an unhelpful model still exhausts the budget and reaches `abandoned`.

That holds only because every attempt costs at least 1 — hence `ASSUME MaxCost > 0` and
`Costs == 1..MaxCost`. Any free path breaks it, which is exactly what `Bug2_FreeRetry` demonstrates.

## Why both a safety bug and a liveness bug

`Bug1_Overshoot` is a safety failure: a finite path to a bad state, which any invariant checker
would find.

`Bug2_FreeRetry` is not. Adding an uncharged "clarification" round leaves **every safety property
intact** — the budget is never exceeded, because nothing is ever spent. Only liveness fails, and TLC
reports it as a lasso: a trace ending in `Back to state`, an infinite cycle. An invariant-only
checker cannot see this class of bug at all, and it is the failure mode behind agents that interact
indefinitely without completing. That is the concrete argument for model checking here rather than
a constraint checker.

## The two halves say the same thing

The Dafny implementation is the TLA+ model in executable form, and the correspondence is exact
where it matters:

| TLA+ | Dafny |
|---|---|
| `BudgetSafe` invariant | the loop invariant, and `ensures spent <= budget` |
| `EventuallyTerminates` | `decreases budget - spent` |
| `Costs == 1..MaxCost` | `ensures 1 <= cost <= maxCost` on `Attempt` |
| `phase' \in {"ready","done"}` | `ok`, returned unconstrained |

`Attempt` is deliberately bodiless. An implementation may return anything, so the verifier reasons
about every possibility — the same universal quantification TLC performs over behaviours, and the
same reason neither tool needs to model the LLM itself.

The clearest evidence they are making one argument rather than two is that the same bug breaks both,
in the same place. `Bug2_FreeRetry.tla` fails liveness with a lasso; `BoundedRetryFreeRetry.dfy`
fails with `decreases expression might not decrease`. Termination and liveness are the same claim,
and both rest on every pass consuming something.

## Where TLA+ stops being redundant

On `BoundedRetry` the two tools agree, which is a useful cross-check but also means Dafny alone
would have caught both bugs. `SharedBudget` is where they part.

Several agents draw on one budget. Each runs the logic `BoundedRetry.dfy` already verifies, and each
is individually correct: every agent checks before it spends, and no agent overspends on its own.
Split the check from the reservation — two statements, which is what an implementation writes by
default — and TLC finds this:

```
 8: <Check>    spent = 5   reserved = (a1 :> 0 @@ a2 :> 0)   phase = (a1 :> "checked" @@ a2 :> "ready")
 9: <Check>    spent = 5   reserved = (a1 :> 0 @@ a2 :> 0)   phase = (a1 :> "checked" @@ a2 :> "checked")
10: <Reserve>  spent = 5   reserved = (a1 :> 3 @@ a2 :> 0)
11: <Reserve>  spent = 5   reserved = (a1 :> 3 @@ a2 :> 3)      -- 5 + 6 = 11 > 10
```

Both agents pass the check, because neither has reserved yet. Both then act on a decision that has
since stopped being true. The budget is broken by the *order*, not by either agent's logic.

**There is deliberately no Dafny counterpart to these two.** A loop invariant describes one thread of
control; it cannot say "and meanwhile another agent took the room I just checked for". Verifying
each agent separately — which is all Dafny offers here — finds nothing wrong, because nothing is
wrong with either agent. This is the division of labour: TLA+ for the protocol, Dafny for the
implementation.

The fix is in `SharedBudget.tla`: make the check and the reservation one atomic action, so nothing
can slip between deciding there is room and taking it.

## The task lifecycle, and two things checking it found

`TaskLifecycle.tla` is Table 2 of Allegrini, Shreekumar & Celik, *Formalizing the Safety, Security,
and Functional Properties of Agentic AI Systems* (arXiv:2510.14133v2) — eleven states covering
dependency waiting, dispatch, retry, fallback and cancellation, with TL1–TL14 over them.

The paper states these properties in CTL and never checks them; its own conclusion defers that to
future work. Running them turned up two things.

### TL4 as published forbids cancelling a dispatching task

> TL4: A sub-task in DISPATCHING eventually reaches the IN_PROGRESS state.
> `AG(state = DISPATCHING → AF(state = IN_PROGRESS))`

Read literally, once a task is DISPATCHING it *must* reach IN_PROGRESS — so no cancellation,
timeout or shutdown may intervene. TLC finds the counterexample in two steps: `Dispatch`, `Cancel`.

That is not a constraint any real framework satisfies. Strands exposes `agent.cancel()` and a
`cancel_signal` precisely so in-flight work can be abandoned. The same objection applies to TL2.

`TaskLifecycle.tla` therefore carries both: `TL4_AsPublished`, kept and checked by
`TaskLifecycle_TL4Published.cfg` so the finding cannot rot into a stale comment, and a weakened
`TL4` admitting `CANCELED`, which holds. The divergence is deliberate and recorded, not quietly
patched.

### TL1 is a constraint on the retry policy, not a property of the lifecycle

> TL1: Every CREATED sub-task eventually terminates in COMPLETED, ERROR, or CANCELED.

TL14 says a RETRY_SCHEDULED task dispatches "if the retry policy permits", and nothing in Table 2
says a retry policy must be bounded. `Bug4_UnboundedRetry.tla` takes that at its word, and TL1 fails
as a lasso: `FAILED → RETRY_SCHEDULED → DISPATCHING → IN_PROGRESS → FAILED`, forever.

So TL1 only holds given a bound the paper leaves implicit. That is the same shape as
`Bug2_FreeRetry`: termination rests on every pass through the loop consuming something finite.

### One error of ours, caught the same way

The first version let `FALLBACK_SELECTED` go straight to `ERROR`. TL3 rejected it — the paper lists
that state's successors as DISPATCHING, CANCELED or FAILED, and ERROR is not among them. The model
was wrong, not the property, and checking is what said so.

## HP10, and why it is not independent of TL1

`DependencyDAG.tla` is HP10 from the same paper's Table 1:

> Every sub-task in the Task DAG is invoked only when it has no dependencies on other uncompleted
> sub-tasks.
> `AG(∀i ∈ D : CL.invoke(EE, prot, sub_task_i) → ∀p ∈ parents(sub_task_i) : Completed(p))`

Four tasks, `t1` and `t2` feeding `t3`, which feeds `t4`.

**The gate is not "every parent completed", and getting that wrong was a real bug in this model.**
Strands decides readiness per *edge*, with OR semantics — a node fires on the first incoming edge
whose source completed and whose condition passed — so an unguarded join starts before all of its
parents are done. Modelling it as AND described a stricter orchestrator than the one that runs,
which is the unsound direction. The AND is recovered where it actually lives: in a condition the
workflow author writes, which the translator reads off the edge object. See
[`DependencyDAG/README.md`](strands/DependencyDAG/README.md) for the whole account.

**HP10 on its own is satisfied by a system that hangs.** `Bug5_NoFailurePropagation.tla` removes
orphan cancellation and nothing else. TLC finds the counterexample in a handful of steps: one task
fails, everything downstream of it stays `BLOCKED`, and the graph never finishes.

No invariant is violated. HP10 holds throughout — nothing ran before its parents completed — and so
does `NoOrphanRuns`. Only liveness fails. An orchestrator audited against HP10 alone would pass, and
then hang in production on the first failed sub-task.

So HP10 and TL1 are not independent: satisfying HP10 creates an obligation to cancel the orphaned
subgraph, and Table 1 does not state it. The paper's prose gestures at the right thing — "the
Orchestrator enforces causal isolation and failure containment ... a sub-task does not proceed if any
dependency is FAILED" — but *not proceeding* is only half of it. Not proceeding satisfies HP10 and
breaks TL1. The property set never asks for the other half.

A cyclic dependency graph fails the same way and needs no separate check: every task in the cycle
waits forever, which shows up as termination failing.

### A translation note

The paper's `AG`/`AF`/`AX` map onto `[]` / `<>` / `[][...]_vars`. Its two reachability properties
(HP15, HP16) use `EF`, which has **no TLA+ form** — TLA+ is linear-time and has no existential path
quantifier. The equivalent is to check `[]~P` and read TLC's violation trace as the witness.

TL7, TL8 and TL10 are stated over "previous state", so the model carries `prev` explicitly. That is
a real cost of phrasing properties over history rather than over actions.

## Crossing into Python

`BoundedRetryExtern.dfy` is `BoundedRetry.dfy` with the model bound to real Python. The proof does
not change — the cost bound was always an assumption about the outside world — but the assumption
now has an address.

```dafny
module {:extern "anchor_model"} AnchorModel {
  class {:extern "Model"} Model {
    static method {:extern "attempt"} Attempt(maxCost: nat) returns (ok: bool, cost: nat)
      requires maxCost > 0
      ensures 1 <= cost <= maxCost
  }
}
```

Translating that emits, in `module_.py`:

```python
import anchor_model as anchor_model
...
out0_, out1_ = anchor_model.Model.attempt(maxCost)
```

The extern names decide the emitted call, verbatim, as `module.Class.method`. Dafny also writes an
empty `anchor_model.py` placeholder, which the real `anchor_model.py` in this directory replaces.

**Dafny does emit the `import`.** The reference manual states that "there is no syntax in Dafny to
insert such `import` statements" and that the generated file must be hand-edited. That is not what
happens when the *module* carries `{:extern}` — the import appears. Worth knowing, because designing
around the documented limitation would mean building a post-processing step that is not needed.

The round trip is a test, not a claim: `GeneratedPythonRunsAgainstTheRealModule` translates, writes
the output, drops in the real module, and runs it.

### The boundary is where Dafny's assumption gets enforced

`anchor_model.py` clamps the cost to `1 <= cost <= maxCost` rather than trusting whatever the model
reports. Dafny assumed that clause and cannot check Python, so this is the only place it can be made
true. A miscounted or absent usage field reporting zero cost would break termination; one reporting
more than `maxCost` would break the budget bound. Neither is hypothetical.

## The audit

`DafnyProgram.AuditAsync` enumerates every point where a proof rests on something taken on trust —
bodiless declarations with an `ensures`, `{:axiom}`, `{:verify false}`, `assume` statements, and
`{:extern}` declarations carrying a `requires` or `ensures`.

For `BoundedRetryExtern.dfy` it reports exactly two, both on `Attempt`: one for the requires, one for
the ensures. That is the complete trust boundary of the program, and it is checked by a test — so it
cannot silently grow.

It is also precise about what does *not* count. In `BoundedRetryFreeRetry.dfy`, `Attempt` is reported
and `NeedsClarification` is not, because the latter promises nothing that a proof could lean on.

## Running one by hand

```bash
java -cp lib/tla2tools-1.7.4.jar tlc2.TLC -tool -cleanup \
    -config specs/foundations/BoundedRetry/BoundedRetry.cfg specs/foundations/BoundedRetry/BoundedRetry.tla
```

`CHECK_DEADLOCK FALSE` is set in each `.cfg`. `done` and `abandoned` have no successor action, which
is what termination looks like to TLC; without it, every correct ending is reported as a deadlock.

## What these proofs do not cover

Stated here rather than discovered later:

- **The cost oracle.** The proof assumes reported token counts match what is billed. If the meter
  lies, the invariant is about a fiction.
- **Paths outside the model.** Nothing here proves an implementation cannot call the model somewhere
  the state machine does not describe. That is the refinement obligation, and it is where the
  Dafny-to-Python translation lives.
- **Crash-restart.** If the process dies between reserving and settling, the reservation is lost
  unless it is durable. The model assumes one continuous execution.
