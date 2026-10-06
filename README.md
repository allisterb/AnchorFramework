# Anchor

## About
Anchor is an agentic formal verification framework that uses the [TLA+](https://lamport.azurewebsites.net/tla/tla.html) formal specification language and model checker to formally verify AWS [Dogwood](https://aws.amazon.com/blogs/opensource/introducing-dogwood-runtime-verification-for-ai-agents/) temporal policies, and provides a [Strands Agents SDK](https://strandsagents.com/) agent that allows humans to perform formal verification of these policies using natural language prompts and questions without knowing the technical details of the formal verification language or tools or theory.

Anchor allows developers and engineers and administrators to use the benefits of formal verification without requiring the specialized knowledge and skills formal methods typically demand. It uses a graph-based Strands multi-agent workflow to try to address the [known issues](EXISTING-RESEARCH.md) in agentic formal verification.

Anchor provides:

* A parser and [translator](https://github.com/allisterb/AnchorFramework/tree/master/src/translator) from the Dogwood policy language to TLA+.
* A [specification](https://github.com/allisterb/AnchorFramework/tree/master/specs/policy/TemporalPolicy) that models a large subset of Dogwood temporal policy semantics, validated in [CI](https://github.com/allisterb/Anchor/actions/workflows/build.yml) against the Dogwood unit test and examples corpus.
* A [model property checker](https://github.com/allisterb/AnchorFramework/tree/master/src/checker) that checks:
     * *derivable* property checks, which can be mechanically derived from all policies e.g. "is this policy vacuous or redundant?"
     * *intentional* property checks where a human or agent authors a *property module* to explicitly capture the intent or requirements of a policy e.g. "Does this Dogwood policy forbid all trades without a human interaction for more than 15 minutes?"
* An [input scanner](src/checker/scan.py) that reads a policy's inputs for hidden characters, look-alike names, instructions aimed at a model and markup, before an agent, a browser or a terminal is shown them.
* A self-contained [HTML report](#auditing-a-directory), `findings.html`, that draws each broken policy claim as the session that breaks it, with the reference Dogwood engine's verdict on every decision.
* An [MCP server](https://github.com/allisterb/AnchorFramework/tree/master/src/Anchor.MCPServer) that provides the following tools to agents:
    * The TLA+ SANY parser and a TLA+ evaluator to assist in code generation
    * The Dogwood to TLA+ translator and model property checker 
    * Knowledge resources that an agent can use to author TLA+ specifications and property modules.
* A Strands [agentic workflow](https://github.com/allisterb/Anchor/tree/master/src/agent) for autonomous and HITL generation of Dogwood policy property modules.

* A [CLI](https://github.com/allisterb/Anchor/tree/master/src/Anchor.CLI) that provides command-line access to the framework tools and MCP server and agent workflow launcher .

Anchor's formal verification can proceed in three modes. 

* `check` Mechanically checks a Dogwood policy set file against a mechanically translated base policy specification and an existing TLA+ property module that captures the intent of the policy set. The most precise
mode and it does not require an LLM, but it requires an existing TLA+ property module and the knowledge to author one accurately. 

* `auto` This is the autoformalization mode. The only artifact a human supplies is a natural language brief that describes the intent of the policy set. The agent is handed a vocabulary derived mechanically from
the policy set, a knowledge article on how to write a property module using the Anchor MCP tools and the brief, and it autonomously writes the TLA+ module. It is not given the policy set's rules, and is told to decide its claims from the brief before looking at the policy, though its `evaluate` tool can read the generated rule set. Three models and four gates stand between a property module draft and a acceptance verdict. An accepted property module is model-checked against the policy set in the same run, a BROKEN one replayed in Dogwood as the session that breaks it, and the run ends with the verdicts and a `check --full` run that checks the policy set with the newly generated property module. Needs no formal methods knowledge on the user's part but requires an LLM.


* `hitl` Similar to auto mode but with one additional step: when a gate rejects a property module draft, it asks the person about the problem *requirement*, (never about TLA+), folds the answer into the brief and tries drafting the property module again. Before the property module is used, it reads the claim back in plain English for the user to confirm the intent is accurate. Needs no formal methods knowledge on the user's part but requires an LLM.

> **Property-module drafting is a work in progress.** A drafted module checks exactly the values it
> names, and nothing proves it states what you meant: the gates (compilation, the decision probe,
> mutation scoring, and a second model comparing the claim's plain-English reading with the
> requirement) can only reject. On the [aws2](examples/aws2) example, drafted modules caught 14 of 17
> hand-written policy bugs (`tests/strands/semantic_mutants.py`), including every bug that lets more
> through. The three they missed make the policy too strict: a window widened, or refunds counted
> across accounts, with no claim that what falls outside them is still allowed. That is one sweep;
> drafts vary from run to run. Read each module's `forbids` lines and its value list before trusting
> a verdict.

## Architecture diagram
![Anchor architecture](docs/images/architecture.svg)

## Getting started

### Using Docker


Easiest way to get started is to use Docker:


```bash
docker pull public.ecr.aws/v4q7x8t1/anchor:latest
docker run --rm public.ecr.aws/v4q7x8t1/anchor:latest version
```

The image is on Amazon ECR Public and is built for both `linux/amd64` and `linux/arm64` under the same tag, so Docker pulls the one
that matches your machine and Apple Silicon runs it natively.

The entry point is the `anchor` launcher, so arguments after the image name are the verb and its
options — the container behaves like the command.

```bash
docker run --rm public.ecr.aws/v4q7x8t1/anchor:latest help
```

Your working directory is mounted at `/work`, which is the container's working directory, so paths
read the way they do on your machine and output lands back on it. On Linux you can add
`--user "$(id -u):$(id -g)"` so files come back owned by you.

```bash
# Linux mount $PWD as /work in the container
docker run --rm -v "$PWD:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw

# Windows mount . as /work in the container
docker run --rm -v ".:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw
```

See [Running](###running) for more info and examples of running Anchor.

## Building
### Building Prerequisites
If you want to build from source, you need:
- **.NET 10 SDK.** The projects target `net10.0` and uses C# 14.
- **A JDK, Java 11 or later**, on `JAVA_HOME` or `PATH`. TLC is run out-of-process on a real JVM, so
  a JVM has to be there. 
- **Python 3.13+**
- **Rust 1.85+** for Dogwood. 
### Building

```
git clone --recursive https://github.com/allisterb/Anchor   # or: git submodule update --init
./build.sh -t                                               # Linux, macOS, or git bash on Windows
./build.ps1 -Test                                           # PowerShell
```

`--recursive` matters to also pick up the Dogwood repo.

Run either with `-h` for the full options. Both scripts fetch the native dependencies into `lib/`,
verify them, build the solution, and — with `-t` / `-Test` — run the tests. `lib/` is gitignored, so
a fresh clone needs one of these before its first build.

| | |
|---|---|
| `-c` / `-Configuration` | `Release` (default) or `Debug`. The launchers prefer a Release build, so the default is what they run |
| `-t` / `-Test` | run the tests after building |
| `-s` / `-SkipDependencies` | don't download; files already present are still verified |
| `-f` / `-Force` | re-download even when present and matching |
| `-h` / `-Help` | usage |


### What gets fetched

Two binaries that NuGet or PyPi  cannot supply get automatically fetched:
- **tla2tools 1.7.4** (Java) used two ways: cross-compiled by IKVM for in-process SANY, and run on a real
  JVM for TLC.
- **z3 4.12.1** (native and not currently used by Dogwood policy verification): the solver Dafny shells out to. Taken from
  [dafny-lang/solver-builds](https://github.com/dafny-lang/solver-builds) — the build Dafny itself is
  tested against — rather than the upstream Z3Prover release. 


Both are checked against pinned sha256 hashes on every run, whether just downloaded or already
present, and a mismatch stops the build rather than being repaired silently.

Both binary tools are pinned by their hash. z3 is pinned per platform: each OS gets a different native binary from solver-builds, so one hash cannot
cover them all, and solver-builds publishes no checksums of its own. z3 binaries for Windows and Linux (x64) have recorded CI hashes but macOS does not so there the Anchor build warns and carries
on since z3 is not part of the Dogwood policy checking path. What Anchor never does is fetch a binary it cannot verify.

### The Python environment

The build scripts do not create it, and neither does anything else: nothing in this repo installs
packages as a side effect of compiling. Two steps, by hand, once.

```bash
py -3.13 -m venv python                 # Windows
python3.13 -m venv python               # Linux, macOS

requirements\strands\install.cmd        # Windows
./requirements/strands/install.sh       # Linux, macOS
```

**Name the version rather than saying `python3`.** Where `python3` is older, the environment is
built with that one silently and the failure surfaces much later, as pip refusing a pin it cannot
satisfy. 

All Python packages installed are hash-pinned. The environment lives at `python/` in the repo root and is gitignored. Anchor looks here by default for its Python tools so a venv made somewhere else has to be named with `ANCHOR_PYTHON`.

## Running

Use the launcher scripts in the repo root:

```
./anchor <verb> [args...]       # Linux, PowerShell, macOS
```

or from a container:
```bash
# Linux
docker run --rm -v "$PWD:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw

# Windows 
docker run --rm -v ".:/work" public.ecr.aws/v4q7x8t1/anchor:latest auto policy.dw --config /config/appsettings.json --intent "..."
```

You can use `ANCHOR_PYTHON` and `ANCHOR_CLI` environment variables to override the Python interpreter and the CLI binary respectively, otherwise the launcher
takes the venv at `python/`, and a Release build before a Debug one under `src/Anchor.CLI/bin`.

### Commands
| verb | action| 
|---|---|
| `check` | check a policy set rule by rule, or against a property module you wrote; with `--full`, audit a policy set or a directory of them — writing `findings.md` and `findings.html` |
| `auto` | draft the property module from a natural-language brief and check it, unattended |
| `hitl` | draft the property module from a natural-language brief and check it, with a human answering when a gate turns a draft away |
| `explain` | say in English what a property module forbids |
| `scan` | read a policy's inputs for hidden text, look-alike names, instructions aimed at a model and markup |
| `timeline` | redraw `findings.html` from the witnesses a check left, without re-running the checks |
| `server` | the MCP server, over stdio or HTTP. The default verb |
| `help [verb]` | get command-line help on [verb]|


### Using LLM models
The agentic modes: `auto` and `hitl` need a model which can be specified in an appsettings.json file and passed to the Anchor CLI e.g.
```bash
# From the repo root, with the appsettings.json file in /config
./anchor auto policy.dw --config /config/appsettings.json --intent "..."

# Linux mount ~/.anchor as /config in the container
docker run --rm -v "$PWD:/work" -v "$HOME/.anchor:/config:ro" public.ecr.aws/v4q7x8t1/anchor:latest auto policy.dw --config /config/appsettings.json --intent "..."

# Windows mount $USERPROFILE\.anchor as /config in the container
docker run --rm -v ".:/work" -v "$($env:USERPROFILE)\.anchor:/config" public.ecr.aws/v4q7x8t1/anchor:latest auto policy.dw --config /config/appsettings.json --intent "..."
```

You can also specify the environment variable `ANCHOR_APPSETTINGS` as a an alternative to `--config` to point to the appsettings.json file. 

The appsettings.json file should contain the model provider and model name, as well as any necessary credentials (e.g., API keys) for the model provider.
A single `-e GEMINI_API_KEY` also works if a key is all you need. A `--config` or `ANCHOR_APPSETTINGS` path that is not there is refused with exit 2. 

The command `check --full` takes a `--config` param or `ANCHOR_SETTINGS` env var too, for the LLM that answers `questions.md`. 
Without either, the file is looked for beside `src/agent/` and at the repo root — which
is where a checkout keeps it and where an image has neither.  never a fall back to the search, so a different file's key is not used
by accident. Every LLM mode warns about it before its first call, even when the environment
supplies the key, because the file's `Model` and `Region` settings then quietly stop applying.


In the sections below we'll use
```
anchor
```
as an alias for either the launcher script in the repo root or the Docker container launch command with the appropriate directories mounted.

### Verifying a Dogwood policy set file

#### Vocabulary

* A **policy** is one `permit` or `forbid` statement, and a `.dw` file is a **policy
set**, which Dogwood's term, after Cedar's `PolicySet`. Anchor also calls a policy a **rule**, as AWS's own
Dogwood posts often do, because "the policy" is otherwise ambiguous between one statement and the
file. Every question below is about what the whole set decides. 

* A **session** is one AgentCore
[*policy session*](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html):
the history of related requests a temporal condition can see. Anchor checks every possible session
up to `--attempts` attempts long (3 by default), not one that was recorded.


#### Check mode
```bash
anchor check my_policy.dw
```

This mode uses the TLC model checker and Anchor's Dogwood semantics specifications to answer three questions about a Dogwood policy set, each answered with a **witness session** or a bounded
no.  There is nothing to configure and no property module or intent brief is required.

| question | verdicts |
|---|---|
| Can this permit ever grant anything? | live / **VACUOUS** |
| Is this rule load-bearing, or can it be deleted? | live / **REDUNDANT** / **DEAD** |
| `--against other.dw` — did this edit change a decision? | **THEY DIFFER** / no difference |

e.g.
```
  permit #1  action == Trade         live        witness: Approve -> Trade
  permit #2  action == Trade         REDUNDANT   deleting it changes no verdict in any session
  forbid #3  action == Approve       DEAD        deleting it changes no verdict in any session
```

Nothing about the policy is hand-modelled. The `.dw` text is parsed by the same parser whose reading
agrees with the reference implementation on 911 recorded pairs, and evaluated by the same
`DogwoodSemantics!Decide`, so what is model-checked is the policy **as written** rather than as
paraphrased.

### What it finds that reading the file does not

| | |
|---|---|
| **One word apart, opposite security properties** | a gate on `Approve::response` requires an approval that *completed*; the same rule on `::request` matches somebody having *tried*. AgentCore records a request for every attempt, so the second grants exactly the capability the approval existed to protect — off a run of refusals. `::request` is the conventional form, 555 policy files to `::response`'s 94. |
| **A permit killed by an unrelated rule** | forbid the approval and the sell permit still parses, still validates, still names the action — and authorizes nothing. It is not a weak control, it is zero control, and nothing in its own text says so. |
| **A policy's meaning is not in its own text** | an `event.dwschema` can `pin` a field into every predicate. The policy never writes it, cannot see it, and cannot bypass it. Declared on *every* event kind it also partitions the trace, which changes what `previous` means — two files with the same policy and the same trace get opposite verdicts. |

**Read the result backwards.** TLA+ is linear-time and has no `EF`, so reachability is asked by
checking the negation and reading the counterexample as the witness. A TLC *violation* means the
permit can grant — the good outcome. The tool inverts that before printing, because the raw reading
is a trap.

**VACUOUS is the answer that must never be wrong**, since it tells someone a control is dead and
the obvious response is to delete it. It is falsification-tested rather than merely observed, and
anything that is not an answer — a parse error, an unsupported construct — raises rather than
reporting vacuous. Constructs outside the modelled subset are refused with a reason, never
approximated.

### Auditing: `--full`

```bash
[./]anchor check examples/aws1 --full                    # every policy set in the directory
[./]anchor check examples/aws1/agent-policy.dw --full    # one policy set on its own
```

Without `--full`, `check` checks each policy set rule by rule — one file or every `.dw` in a
directory — prints the verdicts and writes nothing. It ends by listing what it did not use: the
property modules whose header names a policy set, and the questions in `questions.md`.

With `--full` it audits the same policy set or directory. It also runs every `.tla` property module
whose header names a policy set, and asks the `questions.md` questions of an LLM (`--no-llm` skips
them). It writes `findings.md`, the written report, plus `results.json`, a `traces/` directory
holding a re-runnable witness for every broken claim, and **`findings.html`**: one page that draws
each broken claim as the session that breaks it, with the reference engine's verdict on every
decision, the rule that decided it, and the window or total that rule looks at. A directory's report
goes into the directory; a single policy set's into `<policy-set>-findings/` beside it, so it never
overwrites the directory's.

For a single policy set, `--full --property Other.tla` checks a module as well as the ones found by
header: one kept elsewhere, not yet given the header, or written for several policy sets. It is
added, never substituted, and the report marks it as given.

Both modes start by saying what they are about to do, from the options given: what is checked and
how exhaustively, under which reading, which property modules and questions, which LLM and where its
credentials come from, and where the report goes. Anything that can be known to be wrong is said
there too, before the first TLC run.

**The LLM is the optional part of an audit.** `--llm` picks the model for one run; to name it once,
set `Gemini:Model` or `Bedrock:Model` in `appsettings.json` (see
[model-providers.md](docs/model-providers.md#choosing-the-model)). Without `--llm`, `--provider` or `--config`, an LLM that
cannot be reached (no key, no credentials, a key with no region) is a warning: the questions are
skipped, every check runs, and the report says why. Naming any of the three is a request for LLM
calls, so it is proven before the run with a one-token test request through the same client the
questions use: a bad key, an unknown model id, a model the account may not call, or one that cannot
take tools stops the run before it starts (exit 3). A question that still fails at the call gets
the report written, then exits 3. Without any of the three nothing is spent on the test, and an LLM
problem found at the first question is a warning. So `--full --provider auto` is how to say "use
the LLM I have configured, and stop before the run if it cannot be reached". A directory with no property module is a warning
too: the rule-by-rule checks still run, and the report says what they cannot establish.

`findings.html` is a single file with nothing beside it, so it can be attached to a ticket and opens
the same from disk as from a server. It quotes policy text, and a policy under analysis is often one
nobody trusts, so everything it shows is escaped, and its Content-Security-Policy allows exactly its
own inlined renderer and stylesheet, by hash — nothing else runs, loads or connects.
`anchor timeline <dir>` redraws it from the witnesses already there, without re-running the checks.

### Scanning the inputs

```bash
[./]anchor scan examples/aws1
```

A policy's text reaches a model in `auto`, `hitl` and an audit's questions, a browser in
`findings.html`, and a terminal in every verb. `anchor scan` reads it first, for anything that would
act on one of those, or that makes the policy say something other than what it shows:

| severity | what |
|---|---|
| high | bidi overrides and other invisible characters; the Unicode Tag block; control characters and terminal escapes; a name that mixes scripts, such as an action name spelled with one Cyrillic letter that looks Latin; any of those written as a string escape so the file looks clean; instructions aimed at a model; HTML or script markup; an encoded blob that decodes to either |
| medium | non-ASCII in a name, private-use characters, a remote image in markdown, a file that is not well-formed UTF-8, an encoded blob of readable text |

It knows where comments, strings and code are in each language, and it matches phrases against what
a line *looks like* rather than its bytes, so a look-alike letter or a zero-width space inside a word
does not get an instruction past it. Accented names, typography and box drawing are not findings.

The agentic modes run it before a model is shown anything. A high finding stops `auto` and `hitl`
with exit 2. In an audit (`check --full`) the checks still run in full — they are deterministic, and not at
risk from text aimed at a model — and only the model's questions are withheld. It is a heuristic, and
says so: a comment that *discusses* prompt injection will trip it, so `--allow-flagged-input`
proceeds anyway, for findings you have read, and every report records that it was used.






## Project Layout

| Path | |
|---|---|
| `anchor`, `anchor.ps1` | the launcher: one command over the .NET CLI and the Python entry points |
| `src/Anchor.CLI` | the only executable — `server`, `check`, `explain`, verb-dispatched |
| `src/Anchor.Runtime` | base types for every other project — `Runtime` and its logging, `Result<T>`, process helpers |
| `src/Anchor.Verifiers.Dafny` | parse, resolve and verify Dafny via the DafnyPipeline assembly |
| `src/Anchor.Verifiers.TLAPlus` | SANY in-process via IKVM; TLC out-of-process via `TLCProcess` |
| `src/checker` | the policy checker, the input scanner (`scan.py`), and the report renderer (`report/`) that `findings.html` inlines |
| `tests/Anchor.Tests.Verifier` | tests for both verifiers, and for the Python harnesses below |
| `tests/strands/` | the graph translator, the differential tests and the policy tool, run against the real SDK |
| `tests/policies/` | `.dw` policy fixtures the harnesses are pointed at — inputs, not models |
| `specs/strands/` | models of the SDK's own behaviour: graph readiness, the executor loop, the tool hook |
| `specs/policy/` | what an authorization decision means: Cedar, and Dogwood's temporal policies |
| `specs/foundations/` | properties any agent has: budgets, retry, the task lifecycle |
| `docs/` | framework documentation; `docs/agent/` holds internal working notes — handoffs and task writeups |
| `requirements/` | dependency pins: `strands/` for Python (hash-locked), `dogwood/` for the Rust lockfile |
| `python/` | the Python venv the Strands SDK is installed into (gitignored) |
| `lib/` | native dependencies, fetched by the build scripts (gitignored) |
| `ext/dogwood` | the Dogwood source, a git submodule pinned at a commit verified byte-for-byte against the snapshot that was scanned and audited. Built by CI on Linux. **Never edit** |

## License

Apache 2.0. See [LICENSE](LICENSE).

Third-party code, the binaries this project fetches and redistributes, and what was read but not
incorporated, are disclosed in [NOTICES.md](NOTICES.md).

