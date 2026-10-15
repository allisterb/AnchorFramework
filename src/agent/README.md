# `agent`: Using LLMs to draft TLA+ property modules for verifying Dogwood policies

This module is the part of Anchor that uses an LLM: it drafts property modules from
a requirement written in natural language, and reports what was checked without overstatement.

```bash
# draft a property module from a requirement, and check the policy set against it, unattended
anchor auto examples/aws1/07-trust-decay.dw --intent "After 15 minutes without advisor interaction, the agent loses write access."

# the same, with the user answering when a gate turns a draft away. The requirement is read from
# examples/aws1/intents.md, under the policy set's own heading
anchor hitl examples/aws1/07-trust-decay.dw
```

Every command in this README calls an LLM, so it needs a model configured (see
[Configuration](#configuration)). See [three modes](#three-modes-and-the-axis-they-differ-on) for how the `auto` and `hitl` verbs relate to `check`.

## Model configuration

| | taken by | |
|---|---|---|
| `--config` | `auto`, `hitl` | the settings file holding the model configuration and API key. Sets `ANCHOR_APPSETTINGS`, so there is one answer to which file that is; unlike the variable it refuses a path that is not there, because somebody who typed it named a file. Exit 2 |
| `ANCHOR_APPSETTINGS` | every entry point | the same thing from the environment, for something that wrote the file on your behalf. When set, the usual search (beside `src/agent/`, then the repo root) is not used: a path that is not there means no settings file, never a different one. Every LLM mode warns about it before its first call, even when the environment supplies the key, since the file's `Model` and `Region` then stop applying |
| `--provider` | `auto`, `hitl`, `policy_agent.py` | `auto`, `bedrock` or `gemini`. `auto` picks Gemini when a key is present and Bedrock otherwise — an API key in config was put there deliberately, whereas `~/.aws` exists on most machines whether or not the account can call a model |
| `--llm` | `auto`, `hitl`, `policy_agent.py` | the LLM's model id. Defaults to the provider's `Model` setting (`Gemini:Model`, `Bedrock:Model`), then the provider's own default. See [model-providers.md](../../docs/model-providers.md#choosing-the-model) |
| `--project-dir` | `policy_agent.py` only | the directory policy paths resolve inside; a path escaping it is refused. Defaults to the repo. Only the review agent takes it, because only it reaches the checker through `anchor server`, which it starts with this flag: the containment is the MCP server's, and a model choosing paths is exactly the caller it exists for. `auto` and `hitl` call the checker directly and refuse it as an unrecognized argument |

`repair.py`, `clarify.py` and `author.py` take none of the flags: they use `--provider auto` and the
model from the settings file (`ANCHOR_APPSETTINGS`, or the usual search).

### Model provider

Currently **Amazon Bedrock** or **Google Gemini** are supported `--provider auto|bedrock|gemini`.
Documentation is in: **[`docs/model-providers.md`](../../docs/model-providers.md)**. The short version:

| | |
|---|---|
| Gemini | a key in `ApiKeys:GoogleAgentPlatform`. An *Agent Platform* key also needs the `Google` block — without it, `403 API_KEY_SERVICE_BLOCKED` |
| Bedrock | a bearer token in the environment (`AWS_BEARER_TOKEN_BEDROCK`), which `ApiKeys:AmazonBedrock` is put into for you, plus a **region** — with a key, `~/.aws` is not read, so nothing supplies one. Ordinary AWS credentials work too |

Copy [`appsettings.json.example`](appsettings.json.example) to `appsettings.json` here. It is
gitignored by `**/*appsettings.json`; the `.example` is not.

## The three Anchor modes for agentic formal verification

The main diffrentiator between the three modes is *how much of the formalization is yours.* Nothing else about them differs: `hitl` is the
`auto` graph with one node added, and both run the same model-checker `check` does.

| | who provides the property module | how to run it |
|---|---|---|
| `check` | the user | `anchor check policy.dw --property claim.tla`, or `--full` to audit a policy set or a directory |
| `auto` | the agent, autonomously | `anchor auto policy.dw --intent "..."` |
| `hitl` | the agent, with user input | `anchor hitl policy.dw` |

## `auto` mode
Anchor's auto mode runs the entire property module authoring pipeline autonomously, as a Strands Agents `Graph`:
```
describe ─┬─> draft ─> preflight ─┬─> score ─┬─> review ─┬─> check ─> answer ─> report
          │                        │          │           │                        ^
          └────────────────────────┴──────────┴───────────┴────────────────────────┘
                                    every rejection reports
```

**The agent that drafts the property module is not the agent that answers with it.** Asked for both an
artifact and its specification, a model finds a trivial specification the cheapest way to pass. So the draft and answer nodes are
so are two separate agents, and Strands `GraphBuilder` enforces it: one `Agent` instance cannot be two nodes,
and neither sees the other's context. Only `draft` and `answer` are model calls. The other five graph nodes are
`Computed` nodes — ordinary Python behind the `Model` interface, so the graph is uniform while the
criteria stay in code.

The drafter agent is the only graph node with tools. It holds three
[mechanical checks](drafting.py): `check_module` (does the TLA+ property module compile, does it evaluate),
`what_it_forbids` (the plain-English reading and the state counts) and `evaluate` (the value of one
expression). Local `@tool` functions calling the same Python the gates call — not MCP, which would
add a server process and break the hermetic harness.

**What the drafter agent deliberately cannot reach is `score`.** A model that can run mutation scoring will tune
the property until it catches a mutant — optimising against the gate instead of stating the
requirement, a documented failure mode in agentic verification. 

`auto` options:
| flag | default | note |
|---|---|---|
| `--rounds` | 3 | drafting attempts. One model call plus ~1s of SANY each |
| `--turns` | none | agent loop iterations **per call** — not cumulative, so `--rounds R --turns T` allows `R×T` |
| `--total-tokens` | none | input+output per call |
| `--output-tokens` | none | generated per call. Soft — checked at turn boundaries |
| `--max-node-executions` | `2 × stages` | a backstop; hitting it produces **no findings.md** |
| `--node-timeout` | none | a timed-out node fail-fasts the run |
| `--mutants` | 8 | how many broken policies the `score` gate tries |

A tripped token cap is returned by Strands it as a `stop_reason`
(`limit_turns`, `limit_total_tokens`, `limit_output_tokens`) with the agent returning normally.
`Graph` maps only `"interrupt"` to a non-completed status — so a capped node is `COMPLETED` with a
truncated answer. A tripped token cap that leads to cut-off **draft** or **report** is treated as a failed
round. Any token cap that fires is also printed to stderr
as `CAP:` and leads findings.md.

findings.md ends with a table: tokens in/out/total and seconds per model call, then wall clock per
stage. The same totals go to stderr.

## Sweeping a directory

```bash
anchor auto examples/aws2 --intents examples/aws2/intents.md
```

One pipeline per policy with a **stated intent**, read from `intents.md` — `## <policy>.dw`
headings with the requirement under each. Policies enumerated from the directory, not from the
intents file, so one with no stated requirement is *named* in the summary rather than skipped
quietly; a sweep that silently covers two thirds of a directory is a green that means nothing.

The intent has to come from somewhere the policy did not write, which is why it is a separate file.
For `examples/`, each entry is the article's own sentence and is repeated verbatim in the policy's
header comment so the transcription can be checked. **The drafter sees neither** — `describe` hands
it the generated vocabulary and nothing else.

Writes `anchor/<policy>/findings.md` per policy and `anchor/summary.md` over the set.


## `hitl` — the same pipeline with a person as one of the gates

```bash
anchor hitl examples/aws1/07-trust-decay.dw \
    --intent "After 15 minutes without advisor interaction, the agent loses write access."
```

`--intent` is the same flag and the same string `auto` takes; `--brief` remains as an alias. Omit
both and `hitl` reads the requirement out of `intents.md` beside the policy — the file `auto` sweeps
a directory with, so a requirement written once is reachable from either mode. `--intents` names it
somewhere else.

**What it will not do is guess.** A heading matching the policy's filename is taken and shown. An
intents file about a policy *set* states a requirement per heading and none of them is the filename,
so those are listed and the person picks one — by name, or by typing the requirement instead. A
session started on the wrong requirement looks exactly like one started on the right one until it
ends, which is why the ambiguous case costs a question rather than a guess. This is the one place
the two modes must differ: `auto` has to fail where nothing is stated, because there is nobody to
ask.

[`hitl.py`](hitl.py) runs the pipeline autonomously and turns to a person only where
autoformalisation has no oracle. Everything downstream of a property module is mechanical — does it
compile, does the decision vary, does it catch a mutant, does it hold — and each of those is a
criterion in code that cannot be talked out of its answer. Everything *upstream* is somebody saying
what they meant, and nothing here can check a property against an intention nobody wrote down. A
live sweep over `agent-policy.dw` accepted **one requirement in five**, and the four that failed
failed on the semantic gate rather than on syntax: well-formed statements of something the brief
did not quite say.

```
brief ─> [ the graph ] ─> passed? ─ yes ─> checked, and reported
           ^                 │
           └── clarify ──────┘        bounded by --refinements, and every exit reports
```

**The person is never shown TLA+.** Each gate already knows what went wrong in terms of the policy
and the brief; `ask_about` turns that into a question about the *requirement*, and the answer is
appended to the brief before the graph runs again.

| what fired | what the person is asked |
|---|---|
| the decision never varies | *what has to have happened BEFORE the request you care about?* |
| the claim cannot fail | *which exact values should this be checked at?* |
| it catches no mutant | *name one thing it must never allow, **and one it must allow*** |
| the reviewer disagrees | both texts, side by side — and `keep` **overrules** it |
| the allowance ran out | say it again, with the policy's own vocabulary shown |

The order is the diagnosis: a policy that refuses everything the property names *also* fails
mutation scoring, and "what would a broken policy do" is unanswerable while the real answer is a
missing prior approval. What no clarification can fix — an unreachable model, an unparseable
policy, a bug in Anchor, a module that compiled and then died on the tagging discipline — is
**not** put to a person; the loop stops and says so.

**The mutation question asks for both directions, and that was learned the hard way.** It used to
ask only *"name one thing this policy must never allow"* — and a drafter answering that faithfully
writes claims that all say something must be REFUSED. Every mutation tried removes or narrows a
permission (a rule deleted, a permit typed as a forbid, a condition dropped), so a policy that
refuses *more* still refuses everything such a property demanded be refused: it survives all of
them and is rejected for constraining nothing. **The question produced the property the gate then
turned away**, and three live sessions went round that loop before it was spotted. The property
that eventually passed differed from the ones that did not by exactly one claim — a positive one.

**One extra node, `confirm`, between `review` and `check`.** The person is shown, in plain English,
what the claim forbids, *before* any TLC runs — the one step that can catch a property which is
well-formed, discriminating, agreed to by a second model, and about the wrong rule. It costs
milliseconds because `explain` is already in hand from `preflight`.

**The loop is outside the graph**, for the same reason `draft`'s retry is inside one node: a retry
is a cycle. Each attempt is one whole acyclic run of the checked shape, and
[`tests/strands/hitl_loop.py`](../../tests/strands/hitl_loop.py) re-proves `AlwaysReports` over the
graph `build_hitl()` returns — five exclusive decisions now, not four — rather than inheriting it
from a graph this one is no longer identical to.

**Every stage announces itself.** Before the first question can appear the run has to get through
`describe` → `draft` (a model call per round) → `preflight` → `score` (one TLC run per mutant) →
`review` (a second model call), which on a six-field policy is minutes. It printed nothing at all
until a live run showed that this is indistinguishable from a hang — the unattended sweep reports
each policy as it lands for exactly that reason, and the mode with a person sitting in front of
it did not.

**The I/O is injected**, which is load-bearing rather than tidy: `Console` is three methods, and
the harness drives the whole mode with a scripted person and no provider at all. `Terminal` is
stdlib `print`/`input` writing to **stderr**, because stdout carries the session report's path.
Swapping it for a richer renderer touches that class and nothing else.

| flag | default | note |
|---|---|---|
| `--refinements` | 4 | how many times the person may be asked before the session ends |
| `--rounds` | 3 | drafting attempts *within* one pass, before the person is asked |

Writes `anchor/attempt-N/findings.md` per attempt and `anchor/session.md` over the session —
what was first asked for, what the person was asked and said, and a row per attempt. **Being in
this mode is not a confirmation**: a session whose allowance ran out says so, and the footer
credits the person only where they actually reached the checkpoint. It refuses to start without a
terminal, because a mode that asks questions and reads EOF as an answer would spend a model call
per attempt talking to nobody.

## The policy review agent: `policy_agent.py`

```bash
python src/agent/policy_agent.py tests/policies/dead_forbid.dw
python src/agent/policy_agent.py tests/policies/edit_diverges_both_ways.dw --against tests/policies/edit_diverges_both_ways_old.dw
python src/agent/policy_agent.py tests/policies/firewall_open.dw --ask "does this let anything in from outside?"
```

It is a [Strands](https://github.com/strands-agents) agent that starts `anchor server` over stdio
and is an MCP client of it, the same wiring an MCP host such as Claude Desktop uses, so its only
tools are the [`Anchor.MCPServer`](../Anchor.MCPServer) tools and knowledge articles. It drafts
nothing: it answers questions about a policy set, and exists to test whether a model given that
knowledge base, and almost nothing else, reports a verdict with its caveats intact.

**Where it runs.** It is not a stage of `auto` or `hitl`. It runs in two places:

- **`anchor check --full`**, once per question in a `questions.md` beside the policy sets:
  [`audit.py`](audit.py) calls its `review()` and writes each answer, with every tool call it made,
  into `transcript.md` beside the report; `findings.md` counts how many were answered. This is the
  LLM that `--no-llm` skips.
- **On its own**, as above. It has no `anchor` verb; it is a Python entry point.

**Not to be confused with the pipeline's `review` stage**, the second model that judges a drafted
claim against the requirement. That one has no tools and sees two texts. The shared word is a
coincidence of naming, nothing more.

`pipeline.py` and `hitl.py` import `policy_agent` too, but only for its plumbing: building the model
(`build_model`), checking it can be reached (`readiness`), `--config` and error messages. All of the
model-provider setup lives in this file, so everything that calls a model goes through it, without
running the review agent.

### Every model in Anchor, and what it can call

```
anchor auto / hitl ──> pipeline.py: describe ─> draft ─> preflight ─> score ─> review ─> check ─> answer ─> report
                                                  │                              │                  │
                                            local tools                       no tools           no tools

anchor check --full ──> audit.py ──> each question in questions.md ──> policy_agent.review()
                                                                             │
                                                                 MCP tools, via `anchor server`
```

| model | runs in | tools |
|---|---|---|
| the drafter | `auto`/`hitl`, the `draft` stage | three **local Python functions** in [`drafting.py`](drafting.py) (`check_module`, `what_it_forbids`, `evaluate`) calling the checker directly. **Not MCP**: no server process, and the harness runs the pipeline with scripted models and no server. Never the gates that judge it |
| the reviewer | `auto`/`hitl`, the `review` stage | **none**. Shown only the requirement and the plain-English reading of the claims |
| the answerer | `auto`/`hitl`, the `answer` stage | **none**. Handed the verdicts, writes them up |
| the review agent (`policy_agent.py`) | `check --full` for `questions.md`, or on its own | **the MCP tools** and knowledge articles, through `anchor server` |
| `repair.py`, `clarify.py`, `author.py` | on their own | none of their own; the scripts call the checker around the model |

## The system prompt is thin, and that is the experiment

The server ships six knowledge articles saying what each verdict does and does not establish: that
VACUOUS is bounded by `attempts` rather than absolute, that a REFUSAL is not a clean result, that
`unknown` from a smoke run is never grounds for deleting a rule, that without an event schema every
answer assumes a reading which is not the deployed one.

Those articles were written for a model to read. **Until this agent existed, no model ever had.**

So the prompt does not restate them. It says the knowledge base exists and must be consulted before
a verdict is reported. Restating the caveats there would guarantee a well-qualified answer while
proving nothing about whether the knowledge base works — and the knowledge base is what an agent we
did not write would have to rely on.

If a review comes back missing the bound or the reading, that is a finding about the articles or the
tool descriptions. It is not a reason to thicken the prompt.

## The model is isolated, deliberately

A review needs credentials, a network call and a bill. Everything underneath it does not — and that
"everything" is where the mistakes actually live. So it is split:

| | needs a model? | what it proves |
|---|---|---|
| [`tests/strands/agent_wiring.py`](../../tests/strands/agent_wiring.py) | no | the server launches, every tool is advertised, every article is reachable both as a tool and as a resource, a real check runs, containment holds, a refusal is still a refusal — and Bedrock builds a client without reading `~/.aws`, signing with the bearer token, which is what keeps a native dependency out of the lock |
| [`tests/strands/repair_loop.py`](../../tests/strands/repair_loop.py) | no | the repair loop's mechanics: a defect is caught, the objection reaches the next round, the bound bounds, a refusal is data rather than a crash, and `no_widening` is enforced in code |
| [`tests/strands/clarify_readings.py`](../../tests/strands/clarify_readings.py) | no | that a proposed ambiguity is VERIFIED before anyone is asked: readings deciding every session alike are not raised, and an uncheckable one is not counted as agreement |
| `policy_agent.py` | yes | whether a model given only a thin prompt reports honestly |
| `repair.py` | yes | whether a model can act on a counterexample |
| `clarify.py` | yes | whether a model notices that a request admits more than one policy |

That split earned itself immediately. Building the agent found a bug nothing else had: **`CheckPolicy`
hung forever over stdio** — five seconds over HTTP, never over stdio — because `PythonProcess` did
not redirect the child's stdin, so the checker inherited the MCP protocol pipe. Every test passed;
the transport every host actually uses was broken. See `AToolThatSpawnsAChildProcessAnswersOverStdio`.

## The repair loop

```bash
python src/agent/repair.py tests/policies/firewall.dw --ask "also open RDP" --rounds 3
python src/agent/repair.py tests/policies/firewall.dw --ask "tighten this" --no-widening --property tests/policies/firewall.tla
```

`propose → check → feedback → repair`, with [`properties.py`](../checker) as the oracle. The
division is the point:

| | |
|---|---|
| the model | proposes policy **text**, and nothing else |
| `repair.py` | decides what is checked, with what bounds, and whether the result is acceptable |

**The acceptance criteria are arguments, evaluated after the model has spoken.** `--no-widening`,
`--property` and the defect checks are never shown to it as something it may change. That is not
caution for its own sake: a repair loop with nothing held fixed lets the model change what it is
checked against (measured by Lahiri, arXiv:2608.21516: rewritten code, restated goals, bare assumptions). The structural defence is
that the property is not an input it can reach.

`repair()` takes its proposer as an argument, which is what lets the loop be tested without
credentials. A scripted proposer returns known-bad text then known-good text, and the harness pins
what a green loop can silently lack — that the objection actually **reaches** the next round.

**Watch it fail.** Asked to make approvals permitted again under `--no-widening`, which cannot both
be done and not widen:

```
--- round 1: rejected ---
  this is MORE PERMISSIVE than the policy it replaces, and it was required not to add
  permissions. It newly allows:
  1. ApproveSale(stock = 1)  allowed  (approved = false)

--- round 2: rejected ---
  the checker could not produce a verdict... policy body starts with 'where', not when/unless

NO ACCEPTED CANDIDATE after 2 round(s).
```

Round 2 is the interesting one: pressed by an objection it could not satisfy, the model produced
something invalid. The loop reported that and stopped, rather than accepting a plausible-looking
answer — and the run exits 1. **A loop that cannot fail is a loop that will not stop.**


## Drafting a property, and the two gates on it

```bash
python src/agent/author.py examples/aws1/07-trust-decay.dw --name TrustDecay10 \
    --intent "After 10 minutes without advisor interaction, the agent loses write access."
```

The intent comes from **outside** the policy — a requirement, a comment, what somebody asked for.
A property derived from the policy is a restatement of it, and checking a policy against its own
restatement always passes.

A draft is kept only if it could have failed, and there are two gates because there are two ways
to be useless:

| | refuses | how |
|---|---|---|
| **`preflight`** | a claim whose condition no state satisfies; one true by the module's own arithmetic; a `.cfg` naming an invariant that does not exist | [reads](../checker#and-that-failure-is-now-detected-rather-than-described--anchor-explain) the module. Milliseconds |
| **mutation** | a claim that holds of the policy *and* of every small breakage of it — a tautology about the decision, which reading cannot see | one TLC run per mutant |

The first exists because the second is slow: a draft refused by reading costs a second instead of
minutes, and the round it saves is a round spent on a better draft. Neither replaces the other, and
[the harness](../../tests/strands/property_authoring.py) carries a fixture for each that the other
lets through — so a change that quietly collapsed them into one would fail.

**What comes out is a draft**, and the run ends by saying what it forbids rather than by asserting
it is right:

```
  LosesWriteAfter10m
     forbids   gap is greater than 10 * Minute (= 600), and yet the policy GRANTS it
     applies   to 3 of the 6: gap = 840, gap = 960, gap = 1800

THIS IS A DRAFT. ... whether it captures what you meant is the one question no tool here
answers -- the `forbids` lines above are that question, asked in a form you can answer.
```

That is the human checkpoint the literature converges on, at the one boundary where it says
autonomy fails: everything downstream of a property is mechanical, everything upstream is a person
saying what they meant, and the step between is the one nothing verifies.

## Ambiguity, before a policy exists

```bash
python src/agent/clarify.py tests/policies/firewall.dw --ask "also open RDP in addition to SSH"
```

A verifier answers questions about a policy that exists. It cannot tell you the **request** was
ambiguous, because by the time it runs a reading has already been chosen — silently, by whatever
wrote the policy. *In addition to* what, exactly: the same authentication requirement? the same
rate limit? a separate allowance of its own?

**The readings are compared against each other, not merely listed.** A model can always manufacture
a distinction; whether one exists is a question with an answer. Real output:

```
  (a) RDP permitted, but only from the local network, just like SSH
  (b) RDP permitted from any origin; SSH still local-only
  (c) Any connection from the local network is permitted

  (b) is MORE PERMISSIVE than (a) -- it newly allows:
      1. Connect(origin = "external", port = 3389)  allowed

  (c) is MORE PERMISSIVE than (a) -- it newly allows:
      1. Connect(origin = "local", port = 3390)  allowed
```

Those two witnesses are the content. (b) lets RDP in **from outside**; (c) opens an arbitrary port,
which is how you can tell it opened everything rather than just RDP.

**Silence is a feature.** Readings that decide every session alike are not raised, however
different their text — an assistant that asks a clarifying question every time trains people to
click past it. And a reading the checker could not answer about is reported as unchecked rather
than counted as agreement: *"I could not tell"* and *"they are the same"* are different answers and
only one of them is reassuring.

Exit codes: **3** when a person should choose, 0 when there is nothing to ask — so a script can
branch on "needs a human" without parsing prose.

