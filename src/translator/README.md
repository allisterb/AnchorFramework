# `translator`: source artefacts to TLA+

This module provides deterministic parsing from source artefacts to TLA+ specs

| | from | to |
|---|---|---|
| **policies** | Dogwood `.dw` text | the records `DogwoodSemantics!Decide` evaluates |
| **workflows** | a live Strands Agents `Graph` | the definitions `DependencyDAG.tla` checks |

```
.dw text ──> parse ──> policy dicts ──> emit ──> TLA+ records ──┐
               ▲                                ▲               │
         schema (pins)                  trace (events)          ├──> tlc ──> a verdict
                                                                │
GraphBuilder ──> Graph ──> strands_graph_to_tla ──> Workflow.tla ┘
```

| | |
|---|---|
| `parse.py` | the recursive-descent parser for the modelled Dogwood subset, built against the real `.pest` grammar in the reference tree. Refuses anything outside the subset rather than guessing, and names the *feature* it refused rather than the token it tripped over. Macros are expanded here. |
| `schema.py` | reads an `event.dwschema` for the one thing in it that changes what a policy **means**: a `pin`, which forces a field of every event to equal something about the decision. A policy cannot see or bypass it. |
| `emit.py` | the TLA+ data. Every value is tagged with its kind so TLC refuses a cross-kind comparison instead of quietly answering one. |
| `trace.py` | reads an event log into trace records. `@N` is seconds. |
| `tlc.py` | finds the tools jar by glob, and runs TLC. |
| `strands_graph_to_tla.py` | walks a live Strands `Graph` into `Workflow.tla`. `GraphBuilder` is the construction API, so the graph **is** the workflow the runtime executes — walking it is translation, not inference. |
| `dw_to_tla.py` | the script: regenerates `specs/policy/TemporalPolicy/RotationPolicies.tla`. `--check` fails if it has drifted from the `.dw` sources. |

## Strands Agents graph translation limitations

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

**It is deliberately not re-exported from `__init__.py`.** Importing it pulls in the Strands SDK;
importing a policy translator should not. `import translator` loads no `strands` module, and that
is worth keeping true.

## The boundary

The library translates and runs. It does not decide what to check, and it does not decide what
follows from what it translated — that is [`checker`](../checker). Differential harnesses, corpus
walkers and fixture graphs are consumers and live in `tests/`.

The test for whether something belongs here is whether the MCP server would need it to answer a
question about an artefact it was handed.