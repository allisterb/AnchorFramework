# `translator`: source artefacts to TLA+

This module deterministically translates source artefacts into TLA+. It holds **two separate
translators** that share nothing but the TLC runner:

| | from | to | status |
|---|---|---|---|
| [**Dogwood policy translation**](#dogwood-policy-translation) | Dogwood `.dw` text | the records `DogwoodSemantics!Decide` evaluates | what `anchor check`, the MCP server and the drafting agent run on |
| [**Strands graph translation**](#strands-agents-graph-translation) | a live Strands Agents `Graph` | the definitions `DependencyDAG.tla` checks | kept, but **not part of this release's focus**, and not used by the policy translation |

Neither imports the other. `import translator` loads the policy translation only.

## Dogwood policy translation

```
                schema.py: pins     agentcore.py: AgentCore's reading
                              │       │
.dw text ──> parse.py ──> policy dicts ──> emit.py ──> policy_module.py ──> PolicyUnderTest.tla ──┐
                                             │                                                     ├──> tlc.py ──> TLC
event log ──> trace.py ──> trace records ──> cases.py ──> a cases module ──────────────────────────┘
                                                                  both evaluated by DogwoodSemantics.tla
```

| | |
|---|---|
| `parse.py` | the recursive-descent parser for the modelled Dogwood subset, built against the real `.pest` grammar in the reference tree. Refuses anything outside the subset rather than guessing, and names the *feature* it refused rather than the token it tripped over. Macros are expanded here. |
| `schema.py` | reads an `event.dwschema` for the one thing in it that changes what a policy **means**: a `pin`, which forces a field of every event to equal something about the decision. A policy cannot see or bypass it. |
| `agentcore.py`, `agentcore.dwschema` | the AgentCore reading: Dogwood under AgentCore's event schema (`eventPrincipal`/`eventResource`, history per session), plus the rules AgentCore enforces when a policy is created, which Dogwood's validator does not. A policy breaking one is reported as one AgentCore would reject; a construct a one-gateway model cannot answer for under AgentCore is refused. See [`docs/agentcore.md`](../../docs/agentcore.md). |
| `emit.py` | the TLA+ data. Every value is tagged with its kind so TLC refuses a cross-kind comparison instead of quietly answering one. |
| `policy_module.py` | the policy set as `PolicyUnderTest.tla`, the module every check and every property module extends: the rules as records, and the vocabulary (actions, fields and their values) derived from the policy's own text. |
| `trace.py` | reads an event log into trace records. `@N` is seconds. |
| `cases.py` | policies, traces and expected verdicts as one TLA+ module for `DogwoodSemantics` to judge: what the differential harnesses run on. |
| `dw_to_tla.py` | the script: regenerates [`RotationPolicies.tla`](../../specs/policy/TemporalPolicy/RotationPolicies.tla). `--check` fails if it has drifted from the `.dw` sources. |
| `__init__.py` | the public surface, `from translator import parse_policies, ...`: this half only. |

The semantics it targets is hand-written, not generated:
[`DogwoodSemantics.tla`](../../specs/policy/TemporalPolicy/DogwoodSemantics.tla), validated against
Dogwood's own regression corpus and the built engine. **Used by** [`checker`](../checker) (every
`anchor check`), the MCP server through it, the drafting agent through it, and
[`tests/strands/dogwood_differential.py`](../../tests/strands/dogwood_differential.py).

## Strands Agents graph translation

> **Not part of this release's focus, and not used by the policy translation.** It is kept, tested
> and documented here, but nothing a policy check runs depends on it.

```
GraphBuilder ──> Graph ──> strands_graph_to_tla.py ──> Workflow.tla ──> tlc.py ──> TLC, with DependencyDAG.tla
                                    ▲
                   annotations: what each edge condition means
```

| | |
|---|---|
| `strands_graph_to_tla.py` | walks a live Strands `Graph` into `Workflow.tla`. `GraphBuilder` is the construction API, so the graph **is** the workflow the runtime executes — walking it is translation, not inference. |
| [`annotations`](../annotations) | declares what an edge condition means. Lives in a user's own code; this module only reads it. |
| [`specs/strands/DependencyDAG`](../../specs/strands/DependencyDAG) | the spec the generated `Workflow.tla` is checked against. |

**Used by tests only:** [`tests/strands/graph_to_tla.py`](../../tests/strands/graph_to_tla.py)
(fixture graphs against `DependencyDAG.tla` and the real SDK), and `anchor_workflow.py`,
`pipeline_run.py` and `hitl_loop.py`, which translate Anchor's own drafting pipeline graph to check
its shape, `AlwaysReports` among it.

**It is deliberately not re-exported from `__init__.py`.** Importing it pulls in the Strands SDK;
importing a policy translator should not. `import translator` loads no `strands` module, and that
is worth keeping true.

### Limitations

An edge condition is an opaque Python callable, and `strands_graph_to_tla` does not guess what one
means. `meaning()` in [`annotations`](../annotations) decides that, and this module reports what it was told:

- **tier 0** — a combinator carrying its own TLA+ predicate. Meaning by construction.
- **tier 1** — a user's `@condition_schema` assertion. That is a **hole in every proof below it**,
  and it is listed in the generated module's header as one rather than absorbed.
- **tier 2** — no declaration, so the edge is emitted as nondeterministic and nothing about what it
  decides is claimed.

Those declarations live in [`annotations`](../annotations), which is the only part of Anchor that
goes into a user's own code. A meaning is declared where the workflow is written, by whoever wrote
the condition; this module reads it and never decides.

## Shared: `tlc.py`

The one piece both halves use. It finds the tools jar by glob and runs TLC and SANY with the flags
that keep parallel runs from corrupting each other, and on Windows ties every JVM to the calling
process so a timed-out run cannot leave TLC behind. It also evaluates a single expression
(`run_eval`) for `--eval`.

## The boundary

The library translates and runs. It does not decide what to check, and it does not decide what
follows from what it translated — that is [`checker`](../checker). Differential harnesses, corpus
walkers and fixture graphs are consumers and live in `tests/`.

The test for whether something belongs here is whether the MCP server would need it to answer a
question about an artefact it was handed.
