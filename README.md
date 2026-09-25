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
the policy, a knowledge article on how to write a property module, and the brief, and it writes the TLA+ module. It never sees the policy's rule conditions, so what it drafts cannot be a restatement of the policy. Three models and four gates stand between a property module draft and a acceptance verdict. Needs no formal methods knowledge on the user's part.


* `hitl` Similar to auto mode but with one additional step: when a gate rejects a property module draft, it asks the person about the problem *requirement*, (never about TLA+), folds the answer into the brief and tries drafting the property module again. Before the property module is used, it reads the claim back in plain English for the user to confirm the intent is accurate. Needs no formal methods knowledge on the user's part.

## Architecture diagram
![Anchor architecture](docs/images/architecture.svg)

## Getting started

### Using Docker


Easiest way to get started is to use Docker:


```bash
docker pull allisterb/anchor:latest
docker run --rm allisterb/anchor:latest version
```

On Apple Silicon, add `--platform linux/amd64` to the `pull` and to every `run`; it works under
emulation and is slower.

The entry point is the `anchor` launcher, so arguments after the image name are the verb and its
options — the container behaves like the command.

```bash
docker run --rm allisterb/anchor:latest help
```
```bash
docker run --rm -v "$PWD:/work" allisterb/anchor:latest check my-policy.dw
```

 or Windows:

```bash
docker run --rm -v ".:/work" allisterb/anchor:latest check my-policy.dw
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
| `-c` / `-Configuration` | `Debug` (default) or `Release` |
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
docker run --rm -v "$PWD:/work" allisterb/anchor:latest check my-policy.dw
```

| verb | action| 
|---|---|
| `check` | check a policy against a property module you wrote, or audit a directory of them — writing `findings.md` and `findings.html` |
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
[`deploy/Dockerfile.cli`](deploy/Dockerfile.cli) carries all of them — .NET, a JVM, CPython, and the
Rust-built `dogwood` binary — and its entry point is the launcher, so the container *is* the command.

```bash
docker buildx build -f deploy/Dockerfile.cli --platform linux/amd64 -t anchor:latest --load .
docker run --rm -v "$PWD:/work" anchor check tests/policies/firewall.dw
```

Your working directory is mounted at `/work`, which is the container's working directory, so paths
read the way they do on the host and output written beside a policy lands back on the host. On Linux
add `--user "$(id -u):$(id -g)"` so that output is owned by you rather than by the image's user.

`--platform linux/arm64` builds the other architecture. The two **compile** stages always run on the
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

`--config` works outside a container too, and `ANCHOR_APPSETTINGS` is the same thing from the
environment. Without either, the file is looked for beside `src/agent/` and at the repo root — which
is where a checkout keeps it and where an image has neither. A single `-e GEMINI_API_KEY` also works
if a key is all you need. A path that is not there is refused with exit 2 rather than silently
falling back, so a typo fails loudly instead of running with no key.

Dafny and z3 are **not** in it: neither is on the Dogwood policy path, so no verb reaches the
solver. [`deploy/Dockerfile`](deploy/Dockerfile) is a different image and a different shape — the
Bedrock AgentCore service, which answers `POST /invocations` rather than taking a verb.

## Verifying a Dogwood  policy

### Check mode
```bash
[./]anchor check my_policy.dw
```

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

### Auditing a directory

```bash
[./]anchor check examples/aws1
```

Every `.dw` in the directory, each paired with the `.tla` module whose header names it. Beside them
it writes `findings.md` — the written report — plus `results.json`, a `traces/` directory holding a
re-runnable witness for every broken claim, and **`findings.html`**: one page for the policy set that
draws each broken claim as the session that breaks it, with the reference engine's verdict on every
decision, the rule that decided it, and the window or total that rule looks at.

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
with exit 2. In a directory audit the checks still run in full — they are deterministic, and not at
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

