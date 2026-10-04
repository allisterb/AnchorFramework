# Anchor: An agentic formal verification framework for AWS Dogwood temporal policies using TLA+ and Strands SDK

## Inspiration

### The changing software security landscape
The recent explosion of autonomous AI-driven security compromises and AI model sandbox escapes, compounded by the growing prevalence of AI-generated code, has led to a huge amount of anxiety amoung developers and maintainers of cloud-based distributed systems, as well as calls for new kinds of software and software policy verification that are both broadly available and can offer stronger guarantees on the correctness and safety of these systems. 

The deployment of autonomous AI systems across safety-critical cloud
architectures, financial protocols, distributed enterprise workflows etc. as well as the use of autonomous AI agents for vulnerability scanning and exploitation has exposed fundamental limits in conventional validation of distributed system code and policies. Standard testing methods such as unit testing or fuzzing or manual peer review fail to guarantee correctness across all possible inputs that an AI could use, and also fail to keep up with the rapid rate of code production by AI agents. This divergence introduces security-critical vulnerabilities, including authorization bypasses, privilege escalation, and unintended execution pathways. Enforcing boundaries between distributed systems and verifying the correctness of policies that define those boundaries as well as verifying the behavior of AI agents that interpret, author, and refactor these policies, has never been more critical for the software world. 

Modern distributed systems infrastructure increasingly decouples governance rules and policies from underlying application code into domain-specific policy languages such as AWS's Cedar and Dogwood languages. Policies that control security, authorization, and admission-control systems represent the operational domains that are simultaneously the most high-consequence to compromise and the most vulnerable to deliberate attacks by agents which can improvise and exhaustively explore input until they reach cases not covered by traditional testing methods..

As agents become part of mission-critical distributed systems and as more software is being written by agents, the same tools humans use for verifying policies and software must be made available to agents themselves to allow them to autonomosly test and repair and give feedback on the policies and code they write in response to natural language instructions from humans. 

### AWS Dogwood policy language
[Dogwood](https://aws.amazon.com/blogs/opensource/introducing-dogwood-runtime-verification-for-ai-agents/) is an open-source policy and governance language released by Amazon Web Services to control and verify AI agent behavior over time. Dogwood extendes the existing Cedar policy language with the following capabilities and features

* Temporal Policies: Built on Metric First-Order Temporal Logic (MFOTL), Dogwood evaluates agent requests based on a sequence of past actions rather than looking at a single action in isolation. It allows rules to check if prerequisite steps occurred, count how many times a tool was called, or verify if a spending limit was reached before permitting a new action. 
* Session-Awareness: Evaluates rules across a bounded sequence of events within a session (such as a 24-hour lookback window).
* In-Flight Tracking: Counts active, concurrent requests, not just completed ones, to prevent rapid-fire rule bypasses like submitting multiple large money transfers at the exact same millisecond.
* Sequence Control: Requires specific prerequisites, such as ensuring an invoice or human sign-off happens before a payment tool is triggered. 
* Rate and Total Limits: Caps spending, counts actions within a specific time window, or restricts transaction sizes based on prior activity in the same session. 

 Dogwood is built directly into Amazon Bedrock AgentCore to monitor and restrict agent tool calls at the infrastructure layer. But Dogwood policies suffer from the same vulnerabilities as software: an incorrectly written and inadequately tested policy, either by humans or by AI coding agents, can be discovered and exploited by autonomous AI agents with an explict objective of finding vulnrabilities, or by legitimate agents without the correct architectural guardrails and workflows that allows them to autonomously improvise and find vulnerabilites and work around incorrectly written policies to achieve a business goal, to the detriment of security.

### AWS Dogwood automated reasoning

Dogwood is built on Cedar and the Dogwood CLI can compile a `.dw` policy set into ordinary Cedar policies plus an augmented schema. Automated reasoning and formal verification already exists for Cedar policies, and some AR also exists for Dogwood e.g. the `validate` CLI command checkes well-formedness and certain derived properties like vacuity. But no automated reasoning currently exists for Dogwood set or history relative reasoning i.e a large subset of the *semantics* of a temporal policy.


### Agentic formal verification as a defensive measure againt AI-driven explots
[Formal verification](en.wikipedia.org/wiki/Formal_verification) provides a mathematically grounded proof that a software policy or workflow strictly satisfies a formal specification across *all* possible inputs, not only a single or subset of inputs as with traditional testing and runtime verification. However, traditional formal methods have historically suffered from prohibitive engineering overhead: authoring formal specifications required scarce technical expertise. The emerging paradigm of *agentic formal verification* resolves this bottleneck by connecting generative models with automated formal tools such as model checkers, which allow agent-driven  loops for formal verification from natural language human prompts. In such frameworks, generative models propose code, specifications, and intermediate proof steps, while deterministic verification backends mechanically validate candidate outputs, providing structured diagnostic signals and counterexamples that can guide iterative policy investigation and repair.

Agentic formal verification provides one answer to the velocity of AI-driven autonomous compromises, AI-agents becoming part of mission-critical distributed systems and AI-agent developed code being used to implement the components and security policies that govern these systems. Agents can autonomously write core specification modules and properties modules that model both the logic and the intent of policies and then use model checkers to check if these properties are satisfied and produce counter-examples showing where they fail to hold. 

However agentic formal verification systems also have numerous failings and sources of incorrectness. Melding the inherently probalistic and improvisational and goal-driven nature of AI agents with the rigidity and critical correctness requirements of formal verification  require a careful design and gating to produce useful, valid results. A flawed formal verification result is worse than no result at all as it inspires a high-level of confidence in a policy where no such justification or even the inverse may exist.

An agentic formal verification system that models temporal policy semantics and built using an framework like Strands SDK that supports flexible workflow logic and gating is a possible solution to the problem of agentic formal verification of temporal policy languages like Dogwood, and a valuable toolkit in the defensive arsenal of AWS developers against AI-driven attacks.


## What it does
Anchor is a agentic formal verification framework that uses the [TLA+](https://lamport.azurewebsites.net/tla/tla.html) formal specification language and model checker to formally verify Amazon Dogwood temporal policies, and provides a Strands SDK agent that allows humans to perform formal verification of these policies and code using natural language questions and prompts, without knowing the technical details of the formal verification framework or tools or theory.

Anchor allows developers and engineers and administrators to use the benefits of formal verification without requiring the specialized knowledge and skills formal methods typically demands. It uses a graph-based Strands multi-agent workflow to try to address the [known issues](https://arxiv.org/html/2606.05792v1) in agentic formal verification.

Anchor is designed for AWS developers who would like stronger guarantees on the correctness of the Dogwood policies they write to secure their distributed systems. Using Anchor was able to find incorrectness in multiple policies posted in two AWS blog posts:

Article: [*Securing AI agents with temporal policies in Amazon Bedrock
AgentCore*](https://aws.amazon.com/blogs/machine-learning/securing-ai-agents-with-temporal-policies-in-amazon-bedrock-agentcore/)

Findings: [link](https://github.com/allisterb/Anchor/blob/master/examples/aws1/findings.md)


Article: [Authoring Dogwood policies from natural language in Amazon Bedrock AgentCore](https://aws.amazon.com/blogs/machine-learning/authoring-dogwood-policies-from-natural-language-in-amazon-bedrock-agentcore/)

Findings: [link](https://github.com/allisterb/Anchor/blob/master/examples/aws2/findings.md)

An issue with the Anchor findings on the Dogwood project repo is [here](https://github.com/dogwood-policy/dogwood/issues/15).


Anchor provides:

* A parser and [translator](https://github.com/allisterb/Anchor/tree/master/src/translator) from the Dogwood policy language to TLA+.
* A [specification](https://github.com/allisterb/Anchor/tree/master/specs/policy/TemporalPolicy) that models a large subset of Dogwood temporal policy semantics, validated in [CI](https://github.com/allisterb/Anchor/actions/workflows/build.yml) against the Dogwood unit test and examples corpus.
* A [specification](https://github.com/allisterb/Anchor/tree/master/specs/strands) and [Python annotations](https://github.com/allisterb/Anchor/tree/master/src/annotations) that allow Strands SDK users to model multi-agent Strands graph workflows 
* A [model property checker](https://github.com/allisterb/Anchor/tree/master/src/checker) that checks:
     * *derivable* property checks, which can be mechanically derived from all policies e.g. "is this policy vacuous or redundant?"
     * *intentional* property checks where a human or agent authors a check to explicitly capture the intent or requirements of a policy or workflow e.g. "Does this firewall policy block all inbound connections from external addresses?"
* An [MCP server](https://github.com/allisterb/Anchor/tree/master/src/Anchor.MCPServer) that provides the following tools to agents:
    * The TLA+ SANY parser and a TLA+ evaluator to assist in code generation
    * The Dogwood translator and model property checker 
    * Knowledge resources that an agent can use to author TLA+ specifications and properties modules.
* A Strands [agentic workflow](https://github.com/allisterb/Anchor/tree/master/src/agent) for autonomous and HITL formal verification of Dogwood policies.
* A [CLI](https://github.com/allisterb/Anchor/tree/master/src/Anchor.CLI) that provides command-line access to the framework tools and MCP server and agent workflow launcher .

Anchor's formal verification can proceed in three modes. 

* `check` Mechanically checks a Dogwood policy against a mechanically translated base policy specification and an existing TLA+ properties module that captures the intent of the policy. The most precise
mode but to verify intentional properties it requires an existing TLA+ properties module and the knowledge to author one accurately. 
* `auto` This is the autoformalization mode. The only artifact a human supplies is a natural language brief that describes the intent of the policy. The agent is handed a vocabulary derived mechanically from
the policy, a knowledge article on how to write a properties module, and the brief, and it writes the TLA+ module. It never sees the policy's rule conditions, so what it drafts cannot be a restatement of the policy. Three models and four gates stand between a properties module draft and a acceptance verdict. Needs no formal methods knowledge on the user's part.


* `hitl` Similar to auto mode but with one additional step: when a gate rejects a properties module draft, it asks the person about the problem *requirement*, (never about TLA+), folds the answer into the brief and tries drafting the properties module again. Before the properties module is used, it reads the claim back in plain English for the user to confirm the intent is accurate. Needs no formal methods knowledge on the user's part.

### Advantages of agentic formal verification
Integrating autonomous agents into formal verification infrastructure fundamentally alters the economics and operational guarantees of high-assurance software systems.
#### Eliminating the Proof Engineering Bottleneck 
Historically, the cost of constructing formal proofs exceeded the cost of authoring implementation code by one to two orders of magnitude. Agentic pipelines allow formal verification to scale to general software systems and non-specialist users without demanding dedicated formal methods knowledge or teams.

#### Deterministic Truth Signals Versus Generative Judge Models
Evaluating generated AI code with secondary judge models still suffers from issues like the persistence of probabilistic blind spots, sycophancy, and shared hallucinations. Formal verification acts as a non-negotiable filter: candidate code generated by an agent cannot be merged or deployed unless it satisfies the underlying mechanical verifier.

#### Continuous Refactoring and Regression Prevention
In enterprise policy engineering and DevOps workflows, policy changes routinely introduce regressions that remain undetected by standard test suites. Agentic formal verification enables automated continuous verification in CI/CD pipelines. When an AI refactors an existing
permission set or admission rule, the formal engine mathematically tests equivalence against the legacy policy across the entire domain. This allows safe, automated refactoring of mission-critical authorization systems at scale.

### Agentic formal verification critical pathologies, risks, and failure modes

Despite significant advances, deploying autonomous agents within formal verification loops introduces subtle failure modes. Because generative models optimize for task completion, they frequently discover pathological shortcuts that satisfy the mechanical verifier while undermining system security. Anchor is designed to try to remedy the pathologies and risks of agentic formal verification.

#### The Vacuity Trap and Adversarial Specification Gaming
A central risk in agentic formal verification is vacuous verification: a specification that passes the verifier while checking nothing. For TLA+ it is measured. In [TLA+-Bench](https://arxiv.org/abs/2607.23425), 10% of specifications written by leading models pass the TLC model checker, but only 1.7% pass with a property that does any work. [TLA-Prover](https://arxiv.org/abs/2606.06133) names the shortcut directly: an always-true invariant passes TLC on every problem, so a model rewarded only for passing could learn to write one. It treats this as a risk to design against rather than something it observed: its mutation-tested top tier blocks it, and it appeared once across all its checkpoints.

Repair loops show the same failure when nothing is held fixed, and here it has been measured. In Lahiri's [neuro-formal verification](https://arxiv.org/abs/2608.21516) experiments, an agent repairing proofs against Dafny with no frozen artifacts "proved" 98% of known-buggy programs. It rewrote the code, restated the goal, or assumed the result, which effectively discards the property being checked. Mitigating vacuous verification requires mechanical checks, gates the agent cannot edit, and tests that a passing property actually constrains something, all of which Anchor performs.


#### The User-Intent Formalization Gap and Semantic Drift
Formal verification only proves that an artifact conforms to a given mathematical specification; it does not prove that the specification accurately reflects the user's implicit real-world intent for a policy.
When an agent translates informal natural language requirements into formal specifications, semantic subtleties are frequently lost. Automated metrics that evaluate specification quality—such as mutation analysis, symbolic property testing, and reconstruction consistency—are critical to determining whether formal specifications faithfully mirror informal requirements. Anchor calculates these metrics and uses them as gates to accept or reject an autoformalization. 

#### State Explosion
Bounded Model Checking (BMC) like what the TLC checker does guarantees correctness only up to a fixed execution depth. If an autonomous agent relies solely on BMC to certify a loop or recursive policy rule, vulnerabilities lying at depth remain invisible, providing an incomplete
guarantee of mathematical assurance. Anchor allows the user to explictly specify the bounds of BMC and the Anchor knowledge resources and each Anchor report always emphasizes the lack of a finding does not translate into a finding not existing.

## How it works
The Dogwood temporal policy formal verification in Anchor makes use of two main external toolsets:
* The TLA+ language [tools](https://github.com/tlaplus/tlaplus)
* The Dogwood language [tools](https://github.com/dogwood-policy/dogwood)

The first step in Anchor formal verification is to mechanically [translate](https://github.com/allisterb/Anchor/blob/master/src/translator/dw_to_tla.py) a Dogwood policy to a TLA+ spec using the Anchor Dogwood policy parser and semantics specs. With a TLA+ specification module that models the *logic* of the policy, the next step is to obtain a properties module. A properties module extends the core policy specification and defines the *intent* and *requirements* of the policy that you want the TLC model checker to verify.

Anchor modes differ essentially on one thing: how much of the policy properties module formalization the user needs to write.

| | TLA+ properties module author | launched as |
|---|---|---|
| `check` | not required | `anchor check policy.dw` |
| `check` | the user | `anchor check policy.dw --property claim.tla` |
| `auto` | the agent, unattended | `anchor auto policy.dw --intent "..."` |
| `hitl` | the agent, with user feedback | `anchor hitl policy.dw --intent "..."`|

The first `check` mode mechanically translates the Dogwood policy to TLA+ then runs 3 derived property checks which hold for all policies regardless of intent. The checks answer three questions about a Dogwood policy set, each answered with a **witness session** or a bounded no, with no properties module or intent brief needed. Note that this mode is the equivalent of the AR SMT-powered checker that ships with the Dogwood tools:

| Question | Verdicts |
|---|---|
| Can this permit ever grant anything? | live / **VACUOUS** |
| Is this rule effective, or can it be deleted? | live / **REDUNDANT** / **DEAD** |
| `--against other.dw`: Does the difference between two policies cause a difference in policy decisions? | **THEY DIFFER** / no difference |

### Agentic Workflow
Anchor's agentic `auto` and `hitl` modes use the Strands [Graph](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/) multi-agent pattern. `auto` and `hitl` are the same Strands `Graph` with one node's difference. A requirement written in
English goes in; a properties module, a verdict, and a report come out — and between them stand three
**different** language models and four mechanical gates, any one of which can turn a draft away.

```
describe ─┬─> draft ─> preflight ─┬─> score ─┬─> review ─┬─> check ─> answer ─> report
          │                       │          │           │                        ^
          └───────────────────────┴──────────┴───────────┴────────────────────────┘
                 every rejection still reports, and nothing raises
```

| node | what it is | what it decides |
|---|---|---|
| `describe` | code | the vocabulary the property may name, generated **from the policy** by the checker |
| `draft` | **model** | proposes a `.tla` module and its `.cfg` |
| `preflight` | code, static gate | an invariant the `.cfg` names but the module never defines; a claim that nothing it ranges over can break |
| `score` | code, adversarial gate | breaks the policy on purpose and re-checks. A property that still holds of *every* broken policy constrains nothing |
| `review` | **model**, a third one | shown only the brief and a plain-English reading of the claim — never the formal claim, never the policy. The one gate that compares the property against the **requirement** |
| `check` | code | the checks actually run: the derived questions, and the property against the policy |
| `answer` | **model**, a different one | states in prose what the verdicts established |
| `report` | code | `findings.md`, on every path including both kinds of rejection |

Three properties of this shape are what make the result worth anything:

**The agent that drafts the property is not the agent that answers with it.** Asked to produce both
an artifact and its specification, a model finds that a trivial specification is the cheapest way to
pass — the vacuity trap described above. `GraphBuilder` enforces the separation structurally: one
`Agent` instance cannot be two nodes, and neither sees the other's context.

**The drafter never sees the policy's rule conditions.** `describe` hands it the generated
vocabulary, the knowledge article on writing a property module, and the natural-language brief —
nothing else. A property drafted from a policy is a restatement of that policy and will always pass;
a property drafted from a *requirement* can disagree with the rules, which is the only way it can
find anything.

`hitl` inserts one more node, `confirm`, between `review` and `check`: before any model checker
runs, the claim is read back to the person in plain English — what each invariant **forbids**, and
how many of the states it ranges over its condition even applies to — and they say whether that is
what they meant. When a gate turns a draft away, `hitl` asks the person about the **requirement**,
never about TLA+, folds the answer into the brief, and runs the graph again, bounded by
`--refinements`. This is the one boundary the literature identifies as having no oracle behind it,
and it is the only place this mode puts a human.

## How we built it
Anchor is written in C# and Python. 
| Project |Language| Responsibility |
|---|---|---|
| `Anchor.Runtime` | C#|Shared base types, logging. |
| `Anchor.CLI` | C#| CLI access to the framework tools and the MCP server launcher |
| `Anchor.Verifiers.TLAPlus` | C#| Hosts the TLA+ language tools |
| `Anchor.MCPServer` |C#| MCP server implementation providing agents access to the framework tools and verifiers, tools for writing TLA+ specs and knowledge resources.|
| `translator` |Python| Mechanically translate Dogwood policies to TLA+ specifications.|
| `check` | Python|Uses the TLC bounded model property checker for verifyng derived and intentional properties from an input TLA+ policy spec and properties module|
| `agent` | Python | Strands SDK agent orchestrator for HITL and autonomous formal verification|

### `Anchor.Verifiers.TLAPlus`
Anchor uses .NET to host the TLA+ language tools which are written in Java. The SANY parser the MCP tools use is an IKVM .NET [port](https://github.com/allisterb/Anchor/blob/master/src/Anchor.Verifiers.TLAPlus/Anchor.Verifiers.TLAPlus.csproj) of the Java tlatools library. This allows the parser to be used as an ordinary in-process .NET library this is repeatedly called by the MCP tool used by the agent for TLA+ code generation without having to launch an external JVM process everytime. The TLC model checker isn't compatible with IKVM however and must still be launched as a command-line subprocesses.

### `translator`
The premise is that a model written by reading something is a paraphrase, and nothing checks a
paraphrase. So the artifact itself is the input, in both directions:

```
.dw text ──> parse ──> policy dicts ──> emit ──> TLA+ records ──┐
               ▲                          ▲                     │
         schema (pins)             trace (events)                ├──> tlc ──> a verdict
                                                                 │
GraphBuilder ──> Graph ──> strands_graph_to_tla ──> Workflow.tla ┘
```

| | |
|---|---|
| `parse.py` | a recursive-descent parser for the modelled Dogwood subset, written against the real `.pest` grammar in the Dogwood tree. It **refuses** anything outside the subset rather than guessing, and names the *feature* it declined rather than the token it tripped over. Macros are expanded here |
| `schema.py` | reads an `event.dwschema` for the one thing in it that changes what a policy *means*: a `pin`, which forces a field of every event to equal something about the decision. A policy can neither see nor bypass it, and declaring one on every event kind partitions the trace — so two identical policies with different schemas get different verdicts |
| `emit.py` | the TLA+ data. Every value carries its kind, so TLC refuses a cross-kind comparison instead of quietly answering one |
| `trace.py` | an event log into trace records; `@N` is seconds |
| `tlc.py` | finds the tools jar and runs TLC out of process, with a private `java.io.tmpdir` per run so concurrent runs cannot corrupt each other's unpacked standard modules |

### `check`
`translator` decides what a policy *says*. `check` decides what *follows* from it, by asking TLC
questions the policy text cannot answer about itself.

| | |
|---|---|
| `properties.py` | the entry point and the exit codes. Runs the derived questions, a `--property` module, or both; `--against` compares two policies; `--smoke N` trades exhaustion for a random walk |
| `explain.py` | reads a property module and says per claim what it **forbids**, which states it will be checked in, and how many of those its condition even applies to. Runs no model checker. This is what `hitl` reads back to the person, and what the reviewing model is shown instead of the formal claim |
| `witness.py` | turns a counterexample back into the user's own language: the concrete session it stands for, rendered as a Dogwood `.log` trace |
| `engine.py` | the reference engine, asked the two questions only it can answer |

The polarity is *inverted(), and that is the subtle part. TLA+ is linear-time and has no `EF`, so
*can this rule ever grant anything* is asked by checking the negation and reading the violation as
the witness. A TLC *violation* is therefore the good outcome, and the tool inverts it before
printing, because the raw reading is a trap. It also means `--smoke` is backwards from every other
smoke test: a random walk that finds a witness is a *sound positive* — a witness is a witness
however it was reached — while finding none is not a verdict and never means the rule is inert.

**`VACUOUS` is the answer that must never be wrong**, since it tells somebody a control is dead and
the obvious response is to delete it. It is falsification-tested rather than merely observed, and
anything that is not an answer: a parse error, an unsupported construct,  raises rather than
reporting vacuous.

`engine.py` is where the real Dogwood binary comes in, and it settles two things our own parser
cannot settle about itself. Our parser reads a subset, so a refusal has two meanings with one
message: *this construct is outside the subset* versus *this policy is broken*, and `dogwood
check-parse` distinguishes them for about 35 ms. And when a claim is `BROKEN`, the counterexample is
carried back as a `.log` trace and put to `dogwood replay`, so the verdict shown beside the finding
is **the reference engine's, not ours**. Everything here degrades to "not available" and says so
when the binary is absent; it is never reported as a verification finding.

### `agent`
The workflow above is a Strands `Graph`, built with `GraphBuilder`, and the SDK is doing three
specific jobs rather than being a convenient way to call a model in a loop.

**Nodes are the unit of separation, and the SDK enforces it.** `pipeline.build` adds `draft`,
`review` and `answer` as three distinct `Agent` instances. `GraphBuilder` refuses to let one `Agent`
be two nodes, so the drafter structurally cannot also be the reviewer or the answerer, and none of
them inherits another's context. The alternative designs — one agent with three prompts, or agents
exposed to each other as tools — both leave the model able to satisfy its own specification, which
is the failure mode this whole structure exists to prevent.

**Gates are ordinary Python behind the same interface.** `preflight`, `score`, `check`, `describe`
and `report` are `Computed` nodes: they present as graph nodes so the graph is uniform, while the
criteria stay in code where nothing can negotiate with them. Only three nodes in the graph are a
model's decision, and the table above says which.

**Routing is declared, not inferred.** A gate writes a verdict into its own result and two
`verdict()` edges route on it. Those two edges are declared as **one decision**, which is what lets
the graph itself be model-checked: `tests/strands/anchor_workflow.py` translates the live
`GraphBuilder` output into TLA+ and checks four properties over it — among them that every path
reaches `report`, and that no decision can fire both arms or neither. `hitl` adds the `confirm` node
and is re-proved as its own graph rather than inheriting the result, because it is no longer the
same object.

Around the graph:

| | |
|---|---|
| `pipeline.py` | the graph, the stages, and the `auto` entry point |
| `hitl.py` | the refinement loop and the terminal I/O. The loop is **outside** the graph: it runs a whole graph per attempt, asks the person about whatever stopped it, and runs another |
| `author.py` | the drafter's prompts, the preflight and mutation gates, and the assessment that turns a gate's output into a question about the requirement |
| `drafting.py` | the drafter's own tools — compile this module, tell me what it forbids, evaluate this expression. Deliberately **not** the mutation scorer or the reviewer: a model that can run the gate it is being judged by will tune the property until it passes |
| `repair.py` | the checker invocations |
| `invoke.py` | a content-keyed memo over checker runs. Measured on a one-state model, **1.6s of every 2.0s TLC invocation is JVM startup**, so the only lever on a run's cost is invoking TLC fewer times |
| `policy_agent.py` | the MCP client, and the model configuration — `--config` / `ANCHOR_APPSETTINGS`, provider selection between Bedrock and Gemini |

The mutation gate is the one worth spelling out. `score` breaks the **policy** — deleting rules,
inverting effects, dropping conditions — and re-runs the property against each broken version. A
property that still holds of a policy with its protections removed is a property that constrains
nothing, and it is rejected however well-formed it is. The mutants are taken breadth-first across
the policy's rules rather than in file order, because a prefix of a grouped list leaves most of a
multi-rule policy untouched — measured as 0 of 8 mutants caught versus 4 of 21 before that was
fixed.

## What's next for Anchor

### Verifying the workflow, not just the policy. 
Anchor already [models](https://github.com/allisterb/Anchor/tree/master/specs/strands/StrandsGraph) Amazon Strands graphs in TLA+, and the model is translated from a live `Graph` object rather than written by reading one. `GraphBuilder` is the construction API, so the graph verified and the graph that runs cannot drift apart. Three specifications exist: the dependency DAG, the Strands executor as it actually runs, and a rate limit under the default *concurrent* tool executor. The hard part is that an edge condition is an opaque Python callable: Anchor makes its meaning **declared rather than guessed**, and an undeclared one is emitted as a hole listed in the generated module's header rather than quietly assumed. Anchor's own drafting pipeline is the first graph put through it. 

Three specifications exist today under `specs/strands/`:

* **`DependencyDAG`** — a multi-agent workflow graph. Does a task ever start before its dependencies finish, and does the graph always terminate?
* **`StrandsGraph`** — the Strands executor *as it actually runs*, rather than the orchestrator a paper would specify.
* **`ToolExecutor`** — a rate limit enforced in `before_tool_call` under Strands' default **concurrent** tool executor. The shipped limiter is correct, for a reason nobody wrote down and no test covers.


Anchor's own property-drafting pipeline is the first thing put through this — the graph in `src/agent/pipeline.py` is translated and checked, so the separation it exists to express (the agent that *drafts* a property is not the agent that *answers* with it) is a proved property of the running system rather than a claim in a README.


### Dafny for workflows that must be *correct*, not merely checked

TLA+ answers questions about a model. Dafny proves things about code that then **runs**. Anchor hosts the Dafny pipeline in-process (`ParseAsync`, `ResolveAsync`, `VerifyAsync`, `AuditAsync`), and the intended shape is: write an agent workflow in Dafny, prove its safety and termination, and compile it to Python against the Strands SDK — so the deployed artifact is the proved one.

One subject is already modelled **both** ways, so the two tools can be compared on the same problem. `specs/BoundedRetry` is an agent retrying against a model that may never produce an acceptable answer, and two things must hold whatever the model does: it never exceeds its budget, and it always stops.

| | TLA+ | Dafny |
|---|---|---|
| never overspends | `BudgetSafe` invariant | loop invariant + `ensures spent <= budget` |
| always stops | `EventuallyTerminates` | `decreases budget - spent` |

Two deliberately broken variants are kept beside it: a wrong affordability check that violates the **safety** property, and an uncharged retry path that violates the **liveness** one — and the Dafny version of the same bug fails its `decreases` clause. Same defect, two tools, two different alarms.
