# Anchor

## About
Anchor is an agentic formal verification framework that uses the [TLA+](https://lamport.azurewebsites.net/tla/tla.html) formal specification language and model checker to formally verify Amazon Dogwood temporal policies, and provides a Strands SDK agent that allows humans to perform formal verification of these policies and code using natural language questions and prompts, without knowing the technical details of the formal verification framework or tools or theory.

Anchor allows developers and engineers and administrators to use the benefits of formal verification without requiring the specialized knowledge and skills formal methods typically demands. It uses a graph-based Strands multi-agent workflow to try to address the [known issues](https://arxiv.org/html/2606.05792v1) in agentic formal verification.

Anchor provides:

* A parser and [translator](https://github.com/allisterb/Anchor/tree/master/src/translator) from the Dogwood policy language to TLA+.
* A [specification](https://github.com/allisterb/Anchor/tree/master/specs/policy/TemporalPolicy) that models a large subset of Dogwood temporal policy semantics, validated in [CI](https://github.com/allisterb/Anchor/actions/workflows/build.yml) against the Dogwood unit test and examples corpus.
* A [model property checker](https://github.com/allisterb/Anchor/tree/master/src/checker) that checks:
     * *derivable* property checks, which can be mechanically derived from all policies e.g. "is this policy vacuous or redundant?"
     * *intentional* property checks where a human or agent authors a check to explicitly capture the intent or requirements of a policy or workflow e.g. "Does this firewall policy block all inbound connections from external addresses?"
* An [input scanner](src/checker/scan.py) that reads a policy's inputs for hidden characters, look-alike names, instructions aimed at a model and markup, before an agent, a browser or a terminal is shown them.
* A self-contained [HTML report](#auditing-a-directory), `findings.html`, that draws each broken claim as the session that breaks it, with the reference engine's verdict on every decision.
* An [MCP server](https://github.com/allisterb/Anchor/tree/master/src/Anchor.MCPServer) that provides the following tools to agents:
    * The TLA+ SANY parser and a TLA+ evaluator to assist in code generation
    * The Dogwood translator and model property checker 
    * Knowledge resources that an agent can use to author TLA+ specifications and property modules.
* A Strands [agentic workflow](https://github.com/allisterb/Anchor/tree/master/src/agent) for autonomous and HITL formal verification of Dogwood policies.
* A [CLI](https://github.com/allisterb/Anchor/tree/master/src/Anchor.CLI) that provides command-line access to the framework tools and MCP server and agent workflow launcher .

Anchor's formal verification can proceed in three modes. 

* `check` Mechanically checks a Dogwood policy against a mechanically translated base policy specification and an existing TLA+ property module that captures the intent of the policy. The most precise
mode but it requires an existing TLA+ property module and the knowledge to author one accurately. 
* `auto` This is the autoformalization mode. The only artifact a human supplies is a natural language brief that describes the intent of the policy. The agent is handed a vocabulary derived mechanically from
the policy, a knowledge article on how to write a property module, and the brief, and it writes the TLA+ module. It never sees the policy's rule conditions, so what it drafts cannot be a restatement of the policy. Three models and four gates stand between a property module draft and a acceptance verdict. An accepted property is model-checked against the policy set in the same run, a BROKEN one replayed in Dogwood as the session that breaks it, and the run ends with the verdicts and the `check --full` command that audits with the new module. Needs no formal methods knowledge on the user's part.


* `hitl` Similar to auto mode but with one additional step: when a gate rejects a property module draft, it asks the person about the problem *requirement*, (never about TLA+), folds the answer into the brief and tries drafting the property module again. Before the property module is used, it reads the claim back in plain English for the user to confirm the intent is accurate. Needs no formal methods knowledge on the user's part.

## Architecture diagram
![Anchor architecture](docs/images/architecture.svg)

## Getting started

### Using Docker


Easiest way to get started is to use Docker:


```bash
docker pull public.ecr.aws/v4q7x8t1/anchor:latest
docker run --rm public.ecr.aws/v4q7x8t1/anchor:latest version
```

The image is on Amazon ECR Public, and pulling it needs no AWS account or login. `latest` is
currently `0.1.3`; pin `public.ecr.aws/v4q7x8t1/anchor:0.1.3` for a fixed version. Docker Hub's
`allisterb/anchor:0.1.0` is the image submitted to the hackathon, kept unchanged while judging runs;
it predates the input scanner and `findings.html`.

It is built for both `linux/amd64` and `linux/arm64` under the same tag, so Docker pulls the one
that matches your machine and Apple Silicon runs it natively, with no `--platform` flag.

The entry point is the `anchor` launcher, so arguments after the image name are the verb and its
options — the container behaves like the command.

```bash
docker run --rm public.ecr.aws/v4q7x8t1/anchor:latest help
```
```bash
docker run --rm -v "$PWD:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw
```

 or Windows:

```bash
docker run --rm -v ".:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw
```

Your working directory is mounted at `/work`, which is the container's working directory, so paths
read the way they do on your machine and output lands back on it. On Linux add
`--user "$(id -u):$(id -g)"` so files come back owned by you.

### Building Prerequisites
If you want to build from source, you need:
- **.NET 10 SDK.** The projects target `net10.0` and uses C# 14.
- **A JDK, Java 11 or later**, on `JAVA_HOME` or `PATH`. TLC is run out-of-process on a real JVM, so
  a JVM has to be there. **The build scripts do not install this** — they check for it and stop if
  it is missing. Everything else they fetch themselves.
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

Two native binaries that NuGet cannot supply:
- **tla2tools 1.7.4** used two ways: cross-compiled by IKVM for in-process SANY, and run on a real
  JVM for TLC.
- **z3 4.12.1** (not used by Dogwood policy verification): the solver Dafny shells out to. Taken from
  [dafny-lang/solver-builds](https://github.com/dafny-lang/solver-builds) — the build Dafny itself is
  tested against — rather than the upstream Z3Prover release. 


Both are checked against pinned sha256 hashes on every run, whether just downloaded or already
present, and a mismatch stops the build rather than being repaired silently.

**z3 is pinned per platform.** Each OS gets a different binary from solver-builds, so one hash cannot
cover them all, and solver-builds publishes no checksums of its own. Windows and Linux (x64) are
recorded and both are built and tested in CI. macOS is not: there the build **warns and carries
on without z3**, since z3 is only the solver Dafny shells out to and no part of the Dogwood policy
path uses it. What it never does is install a binary it cannot verify.

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

The environment lives at `python/` in the repo root and is gitignored. That path is not a
convention — it is where the launcher, `PythonProcess` on the .NET side, and the container image
all look for an interpreter, so a venv made somewhere else has to be named with `ANCHOR_PYTHON`.

## Running

Use the launcher scripts in the repo root:

```
./anchor <verb> [args...]       # Linux, macOS
./anchor.ps1 <verb> [args...]   # PowerShell
```

or from a container:
```bash
docker run --rm -v "$PWD:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw
```

| verb | action| 
|---|---|
| `check` | check a policy set rule by rule, or against a property module you wrote; with `--full`, audit a policy set or a directory of them — writing `findings.md` and `findings.html` |
| `auto` | draft the property module from a natural-language brief and check it, unattended |
| `hitl` | draft the property module from a natural-language brief and check it, with a human answering when a gate turns a draft away |
| `explain` | say in English what a property module forbids |
| `scan` | read a policy's inputs for hidden text, look-alike names, instructions aimed at a model and markup |
| `timeline` | redraw `findings.html` from the witnesses a check left, without re-running the checks |
| `server` | the MCP server, over stdio or HTTP. The default verb |
| `help [verb]` | get command-line help |

`ANCHOR_PYTHON` and `ANCHOR_CLI` override the interpreter and the binary. Otherwise the launcher
takes the venv at `python/`, and a Release build before a Debug one under `src/Anchor.CLI/bin`.

### In a container, with nothing installed

Four runtimes is a lot to ask of somebody who wants to check one policy.
[`deploy/Dockerfile`](deploy/Dockerfile) carries all of them — .NET, a JVM, CPython, and the
Rust-built `dogwood` binary — and its entry point is the launcher, so the container *is* the command.

```bash
./build-docker.sh          # or ./build-docker.ps1
docker run --rm -v "$PWD:/work" anchor check tests/policies/firewall.dw
```

The script tags `anchor:<version>` and `anchor:latest`, where the version is `Directory.Build.props`'
unless you name one: `./build-docker.sh 0.1.1` tags `0.1.1`, and `anchor version` inside the image
reports it. Before the build context leaves your machine it checks that `.dockerignore` still keeps
`appsettings.json` out, and that `ext/dogwood` is checked out, unmodified, at the commit that was
audited. Afterwards it runs `version`, `scan` and `check` inside the new image, once per platform.

It builds `linux/amd64` and `linux/arm64` as **one multi-platform image**, which needs Docker's
containerd image store (Docker Desktop's default for new installs, under Settings > General). `-p`
(`-Platform`) builds just one, e.g. `-p linux/amd64`, and needs no containerd store.

It **pushes nothing**. `-r` names the repository to tag, e.g. `-r ghcr.io/you/anchor`, and the push
commands are printed at the end for you to run; each push carries both platforms under the one tag.
`-n` (`-DryRun`) runs the checks and prints the build command without building. The same build by
hand:

```bash
docker buildx build -f deploy/Dockerfile --platform linux/amd64,linux/arm64 -t anchor:latest --load .
```

Your working directory is mounted at `/work`, which is the container's working directory, so paths
read the way they do on the host and output written beside a policy lands back on the host. On Linux
add `--user "$(id -u):$(id -g)"` so that output is owned by you rather than by the image's user.

Building the platform your machine is not is where the time goes. The two **compile** stages always run on the
build host and cross-compile — `dotnet publish` per RID, `cargo build` per target with the matching
cross linker — so neither an emulated .NET nor an emulated Rust build ever happens. The runtime
stage is not pinned that way, so an arm64 build on an x64 host does run its `apt-get` and its
`pip install` under QEMU, and that is most of the wall time.

The agentic modes need a model, and its configuration is yours rather than the image's. **The
settings file is never built in** — `.dockerignore` excludes `**/appsettings.json` by name, because
a key baked into a layer is a key published to everyone who can pull it. Mount the directory that
holds it, read-only, and name the file:

```bash
docker run --rm -v "$PWD:/work" -v "$HOME/.anchor:/config:ro" \
    anchor auto policy.dw --config /config/appsettings.json --intent "..."
```

`check --full` takes `--config` too, for the LLM that answers `questions.md`. It works outside a
container as well, and `ANCHOR_APPSETTINGS` is the same thing from the environment. Without either, the file is looked for beside `src/agent/` and at the repo root — which
is where a checkout keeps it and where an image has neither. A single `-e GEMINI_API_KEY` also works
if a key is all you need. A `--config` path that is not there is refused with exit 2, so a typo
fails loudly instead of running with no key. An `ANCHOR_APPSETTINGS` path that is not there means
no settings file at all, never a fall back to the search, so a different file's key is not used
by accident. Every LLM mode warns about it before its first call, even when the environment
supplies the key, because the file's `Model` and `Region` settings then quietly stop applying.

Dafny and z3 are **not** in it: neither is on the Dogwood policy path, so no verb reaches the
solver. [`deploy/Dockerfile.agentcore`](deploy/Dockerfile.agentcore) is a different image and a different shape — the
Bedrock AgentCore service, which answers `POST /invocations` rather than taking a verb.

## Verifying a Dogwood  policy

### Check mode
```bash
[./]anchor check my_policy.dw
```

**Vocabulary.** A **policy** is one `permit` or `forbid` statement, and a `.dw` file is a **policy
set** — Dogwood's term, after Cedar's `PolicySet`. Anchor also calls a policy a **rule**, as AWS's own
Dogwood posts often do, because "the policy" is otherwise ambiguous between one statement and the
file. Every question below is about what the whole set decides. A **session** is one AgentCore
[*policy session*](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html):
the history of related requests a temporal condition can see. Anchor checks every possible session
up to `--attempts` attempts long (3 by default), not one that was recorded.

Three questions about a Dogwood policy set, each answered with a **witness session** or a bounded
no — nothing to configure, and no statement of intent required:

| question | verdicts |
|---|---|
| Can this permit ever grant anything? | live / **VACUOUS** |
| Is this rule load-bearing, or can it be deleted? | live / **REDUNDANT** / **DEAD** |
| `--against other.dw` — did this edit change a decision? | **THEY DIFFER** / no difference |

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

