# `agent` — the part that talks to a person

[`checker`](../checker) answers precisely and narrowly: is this rule load-bearing, within this
bound, under this reading of history. None of that helps anyone unless the answer reaches them with
its qualifications attached. This is the part that talks to the person, and its job is **not to
overstate**.

```bash
python src/agent/policy_agent.py tests/policies/dead_forbid.dw
python src/agent/policy_agent.py a.dw --against b.dw
python src/agent/policy_agent.py firewall.dw --ask "does this let anything in from outside?"
```

It is a [Strands](https://github.com/strands-agents) agent whose tools are the
[`Anchor.MCPServer`](../Anchor.MCPServer) tools, reached by launching `anchor server` over stdio —
the same wiring an MCP host uses.

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
python src/agent/repair.py firewall.dw --ask "also open RDP" --rounds 3
python src/agent/repair.py policy.dw --ask "tighten this" --no-widening --property claim.tla
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

## The pipeline, as the graph that runs it

[`pipeline.py`](pipeline.py) is the whole of the above wired as a Strands `Graph`:

```
describe ─┬─> draft ─> preflight ─┬─> score ─┬─> review ─┬─> check ─> answer ─> report
          │                        │          │           │                        ^
          └────────────────────────┴──────────┴───────────┴────────────────────────┘
                 every rejection still reports, and nothing raises
```

**The agent that drafts the property is not the agent that answers with it.** Asked for both an
artifact and its specification, a model finds a trivial specification the cheapest way to pass —
so these are two agents, and `GraphBuilder` enforces it: one `Agent` instance cannot be two nodes,
and neither sees the other's context. Only `draft` and `answer` are models. The other five are
`Computed` — ordinary Python behind the `Model` interface, so the graph is uniform while the
criteria stay in code.

**The drafter has tools; nothing else does.** It was writing TLA+ blind — one prompt in, a module
out, and it found out what was wrong a whole round-trip later. It now holds three
[mechanical checks](drafting.py): `check_module` (does it compile, does it evaluate),
`what_it_forbids` (the plain-English reading and the state counts) and `evaluate` (the value of one
expression). Local `@tool` functions calling the same Python the gates call — not MCP, which would
add a server process and break the hermetic harness.

**What it deliberately cannot reach is `score`.** A model that can run mutation scoring will tune
the property until it catches a mutant — optimising against the gate instead of stating the
requirement, a documented failure mode in agentic verification. The reviewer is absent for the same
reason. So nothing new is checked before `score`; what changes is who drives the loop and how fast
the answer arrives. `check_module` reports in one call the failure that ended three live sessions.

**A gate that rejects is not a failed node.** It completes, writes its verdict into its own result,
and a [`verdict()`](../annotations) pair routes on it — declared as *one* decision, so exactly one
arm fires. A rejection costs nothing downstream (no TLC, no second model call) and still reports.

**The retry is inside `draft`, not in the graph**, and that is a constraint rather than a
preference. A retry is a cycle, and neither model can express one: `oracle` is chosen in `Init` and
never changes, so a retry edge cannot mean "again, then stop", and `StrandsGraph`'s `StartBatch`
increments `runs` with no guard, so a cycle breaks `TypeOK`. Keeping the loop in one node keeps the
graph acyclic and every property proved about it true — at the price that the rounds are invisible
to the model. Only the cheap checks are in the loop: SANY (~1s) and `preflight` (milliseconds).
`score` runs TLC per mutant and stays outside, one shot.

**Limits are ours to set, and two of them end a run with no report.** `--max-node-executions` and
`--execution-timeout` make the executor set `FAILED` and return from the batch loop; `--node-timeout`
fails a node, which fail-fasts. None of those reaches `report`. So the cap is set above what the
graph can use and `--rounds` is what actually bounds the work — running out of rounds still reports.

| flag | default | note |
|---|---|---|
| `--rounds` | 3 | drafting attempts. One model call plus ~1s of SANY each |
| `--turns` | none | agent loop iterations **per call** — not cumulative, so `--rounds R --turns T` allows `R×T` |
| `--total-tokens` | none | input+output per call |
| `--output-tokens` | none | generated per call. Soft — checked at turn boundaries |
| `--max-node-executions` | `2 × stages` | a backstop; hitting it produces **no findings.md** |
| `--node-timeout` | none | a timed-out node fail-fasts the run |
| `--mutants` | 8 | how many broken policies the `score` gate tries |

**A tripped cap does not look like a failure.** Strands returns it as a `stop_reason`
(`limit_turns`, `limit_total_tokens`, `limit_output_tokens`) with the agent returning normally, and
`Graph` maps only `"interrupt"` to a non-completed status — so a capped node is `COMPLETED` with a
truncated answer. Two places that matters, both handled: a cut-off **draft** is treated as a failed
round rather than reaching the gates as a half-written module (where it would be rejected for a
syntax error that was really a budget), and a cut-off **report** says so in its own text, because a
truncated report that doesn't reads as a complete one. Any cap that fires is also printed to stderr
as `CAP:` and leads findings.md.

`policy_agent.py` takes the same three flags. It is the agent that holds the MCP tools, so it is the
one that can loop.

## What a run cost

findings.md ends with a table: tokens in/out/total and seconds per model call, then wall clock per
stage. The same totals go to stderr.

**The graph's own totals are not used and cannot be.** Every stage is an `Agent` whose model is
`Computed`, which reports zero tokens because it makes no model call — the two real calls happen
*inside* those nodes. `result.accumulated_usage` is therefore zero for this pipeline, and reporting
it would say the run was free.

**Tokens are read per call, not from the running total.** `metrics.accumulated_usage` is cumulative
across every invocation of the same `Agent` object, and the drafter is reused each round — so
reading it per call bills round 1 again on round 2. Measured here: 15, 30, 45 across three calls
that each cost 15, against a flat 15 from `metrics.agent_invocations[-1].usage`, which is what this
uses. The same trap is recorded in [`tests/strands/shared_budget.py`](../../tests/strands/shared_budget.py);
this is the second place it has come up.

Most of the wall clock is TLC, in `score` and `check`, and costs no tokens — so the report says
which part of the total was model calls.

The shape was chosen by checking four properties against four wirings in
[`tests/strands/anchor_workflow.py`](../../tests/strands/anchor_workflow.py), and
[`tests/strands/pipeline_run.py`](../../tests/strands/pipeline_run.py) re-proves `AlwaysReports`
over the graph `build()` actually returns — so the shape that was checked and the object that runs
are the same object rather than two things that agree today.

```bash
python src/agent/pipeline.py examples/aws1/07-trust-decay.dw \
    --intent "After 15 minutes without advisor interaction, the agent loses write access."
```

**Nothing aborts it.** A node that raises ends the run with no findings.md at all — and that is the
hole `AlwaysReports` cannot cover, since it is stated over `phase = "DONE"` and the property cannot
be strengthened (the model lets *any* node fail). So the obligation is discharged in code: every
stage catches, an unreadable policy is a `describe` gate rejection rather than an exception, and a
stage that crashes anyway says in findings.md that **Anchor** failed — not the policy.

## Sweeping a directory

```bash
python src/agent/pipeline.py examples/aws2 --intents examples/aws2/intents.md
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

## Three modes, and the axis they differ on

**How much of the formalization is yours.** Nothing else about them differs — `hitl` is the
`auto` graph with one node added, and both check what `check` checks.

| | who writes the property module | how to run it |
|---|---|---|
| `check` | you | `anchor check policy.dw --property claim.tla`, or `--full` to audit a policy set or a directory |
| `auto` | the agent, unattended | `anchor auto policy.dw --intent "..."` |
| `hitl` | the agent, with you | `anchor hitl policy.dw` |

`anchor` is the launcher at the repo root — `./anchor` on Linux and macOS, `./anchor.ps1` under
PowerShell. It dispatches on the verb, forwards the rest verbatim and passes the exit code through.

**Only the first of those three is a CLI verb; `auto` and `hitl` are Python entry points, and that
is deliberate.** A verb for either would be a passthrough: the C# would re-declare every flag
`argparse` already has — so each option would live in two places, and adding one to the Python
would leave it unreachable — and then spawn Python anyway. The process hop buys nothing, and the
extra layer is what makes stdio behave differently than expected, which matters most for the mode
that reads answers from a terminal. `check` and `server` stay in the CLI because they are genuinely
C#-fronted. The launcher is where the two halves meet, and it is one dispatch table rather than a
second copy of every option.

Nothing is hidden by it: `anchor auto ...` and `python src/agent/pipeline.py ...` are the same run,
and the Python form is what the rest of this file writes.

## `hitl` — the same pipeline with a person as one of the gates

```bash
python src/agent/hitl.py examples/aws1/07-trust-decay.dw \
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
python src/agent/clarify.py firewall.dw --ask "also open RDP in addition to SSH"
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

## Configuration

| | |
|---|---|
| `--config` | the settings file holding the model configuration and API key. Sets `ANCHOR_APPSETTINGS`, so there is one answer to which file that is; unlike the variable it refuses a path that is not there, because somebody who typed it named a file. Exit 2 |
| `ANCHOR_APPSETTINGS` | the same thing from the environment, for something that wrote the file on your behalf. When set, the usual search (beside `src/agent/`, then the repo root) is not used: a path that is not there means no settings file, never a different one. Every LLM mode warns about it before its first call, even when the environment supplies the key, since the file's `Model` and `Region` then stop applying |
| `ANCHOR_CLI` | path to `Anchor.CLI.dll`, or to a self-contained executable. Otherwise a Release build is preferred, then Debug |
| `--project-dir` | the directory policy paths resolve inside; a path escaping it is refused. Defaults to the repo, and the agent is exactly the caller containment exists for |
| `--provider` | `auto`, `bedrock` or `gemini`. `auto` picks Gemini when a key is present and Bedrock otherwise — an API key in config was put there deliberately, whereas `~/.aws` exists on most machines whether or not the account can call a model |
| `--llm` | the LLM's model id. Defaults to the provider's `Model` setting (`Gemini:Model`, `Bedrock:Model`), then the provider's own default. See [model-providers.md](../../docs/model-providers.md#choosing-the-model) |

## The model: Amazon or Google

Either **Amazon Bedrock** or **Google Gemini** — `--provider auto|bedrock|gemini`. Nothing else in
Anchor changes when you switch; only this last step needs an account.

Configuration, the setup each provider needs, and what each is verified to do live in one place:
**[`docs/model-providers.md`](../../docs/model-providers.md)**. The short version:

| | |
|---|---|
| Gemini | a key in `ApiKeys:GoogleAgentPlatform`. An *Agent Platform* key also needs the `Google` block — without it, `403 API_KEY_SERVICE_BLOCKED` |
| Bedrock | a bearer token in the environment (`AWS_BEARER_TOKEN_BEDROCK`), which `ApiKeys:AmazonBedrock` is put into for you, plus a **region** — with a key, `~/.aws` is not read, so nothing supplies one. Ordinary AWS credentials work too |

Two facts belong beside the code rather than in that document, because they are why
`build_bedrock_model` looks the way it does:

**botocore resolves the credential chain when the CLIENT is built** — before the bearer token is
consulted, and then discards it, because bearer auth supersedes SigV4 at signing. Walking the chain
can therefore only fail, never help. `keyed_session` points a scoped session at `os.devnull` for both
AWS config files when a key is present, which is what keeps `botocore[crt]` out of the dependency
list: the provider that needs it is never reached.

**`BedrockModel` refuses `region_name` beside `boto_session`.** A configured profile and a
configured region is an ordinary combination, so the region rides on the `Session`.

Copy [`appsettings.json.example`](appsettings.json.example) to `appsettings.json` here. It is
gitignored by `**/*appsettings.json`; the `.example` is not, because the pattern ends at `.json`.
