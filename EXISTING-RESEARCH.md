# Existing research

Published work that inspired Anchor's approach: AI agents writing formal specifications, with a model
checker or prover checking them, and the checker's output driving the next attempt. Each entry says
what was taken from it and where it shows up in this repository. Articles are written for a general technical reader and are the place to start. Papers are
the research behind them. The TLA+ section lists the TLA+ references Anchor uses.


## Articles

### Formal Verification in the Age of AI

Toby Murray (University of Melbourne). *Toby's Blog*, 5 March 2026.
https://verse.systems/blog/post/2026-03-05-formal-verification-ai/

A verification researcher's view of where AI fits. Formal methods have long traded off three
things, and could have two of them at most:
- **Automatic**, needing no human proof effort. Static analysis and model checking are; interactive
  theorem proving is not.
- **Scalable** to large systems. Static analysis and theorem proving are; model checking is not.
- **Precise**, with no false alarms. Model checking and theorem proving are; static analysis is not.

The trade-off has a post of its own, *The Formal Verification Triangle* (21 October 2025):
https://verse.systems/blog/post/2025-10-21-formal-verification-triangle/

AI does not replace these tools. It turns them into components of a loop:
*propose → check → feedback → repair → decompose → repeat*. The loop needs two things, a correctness
oracle and feedback rich enough to repair from. Model checkers are singled out as a source of that
feedback: a counterexample trace can force an agent to strengthen an invariant.

**In Anchor:** the clearest statement of what Anchor is. TLC is the oracle, and its counterexample,
replayed in Dogwood, is the feedback (`src/agent/pipeline.py`, `src/agent/hitl.py`). It also names
Anchor's cost honestly: Anchor is in the model-checking row, automatic and precise but not scalable,
which is why every verdict is stated "within the bound". It cites *Agentic Program Verification*,
below.

### The Coming AI Revolution in Distributed Systems

Cheng Huang. Personal blog, 24 May 2025.
https://zfhuang99.github.io/github%20copilot/formal%20verification/tla+/2025/05/24/ai-revolution-in-distributed-systems.html

AI agents in GitHub Copilot wrote a TLA+ specification of an Azure Storage feature from its
production source code. The TLA+ model checker found a violation of the main safety invariant. Given
the counterexample trace, the agent identified a real race condition that code review and testing
had missed: an old Paxos primary deleting while a new one added a reference.

**In Anchor:** the same loop on a production system. An agent drafts TLA+, TLC checks it, and the
trace goes back to the agent. The difference is where the specification comes from. Huang's agent
reads the code; Anchor's translates a Dogwood policy mechanically and keeps the agent for the part
that needs judgement, stating what the policy is meant to do.

## Papers

### Can LLMs Write Correct TLA+ Specifications? Evaluating Natural-Language-to-TLA+ Generation

Arslan Bisharat, Brian Ortiz, Eric Spencer, Khushboo Bhadauria, TaiNing Wang, George K.
Thiruvathukal, Konstantin Läufer, Mohammed Abuhamad (Loyola University Chicago). arXiv:2606.05792,
2026. https://arxiv.org/abs/2606.05792

30 language models were asked to write whole TLA+ specifications from the plain-English comments of
specs in the TLA+ Examples repository, with no feedback loop. At best:
- **26.6%** parsed;
- **8.6%** passed the TLC model checker;
- the strongest model tested, given three examples, passed TLC on 26.9%.

Bigger models did not do better, and models specialised for code did worse. The failures fall into
five recurring classes, among them Unicode symbols in place of TLA+'s ASCII operators, and C-style
semicolons.

**In Anchor:** the baseline for asking a model to write TLA+ unaided, and the reason Anchor does not.
- The model of the policy is generated mechanically from the `.dw`.
- A model drafts only the claim about what the policy should do, against a generated vocabulary,
  with the parser's errors fed back to it.
- A claim that passes is still not trusted until the decision probe and mutation scoring show it
  tests something. Passing TLC, the paper's own measure of "semantic correctness", is also passed by
  a claim that is trivially true.

### TLA-Prover: Verifiable TLA+ Specification Synthesis via Preference-Optimized Low-Rank Adaptation

Eric Spencer, Arslan Bisharat, Brian Ortiz, Khushboo Bhadauria, Mujtaba Nazari, TaiNing Wang, George
K. Thiruvathukal, Konstantin Läufer, Mohammed Abuhamad (Loyola University Chicago).
arXiv:2606.06133, 2026. https://arxiv.org/abs/2606.06133

A 20-billion-parameter model trained to write TLA+, using TLC as the reward. The authors name the
obvious way to game such a reward: an invariant that is always true passes TLC on every problem and
says nothing. Outputs are graded in four tiers. The top tier, **Diamond**, mutates the invariant
slightly and requires TLC to then find a violation; an always-true invariant cannot pass. The model
reaches 30% at the top tier, against 8.6% for untuned models. Giving it TLC's error messages and
three more tries did not help: it repeated the same mistake.

**In Anchor:** the reason the model that drafts a claim never gets to run the check that grades it
(`src/agent/drafting.py`). Anchor's mutation test points the other way from TLA-Prover's: it
mutates the *policy* and requires the claim to notice.

### TLA+-Bench: An Execution-Grounded Benchmark and Dataset for Natural-Language to TLA+ Specification Generation

Arslan Bisharat, Eric Spencer, Brian Ortiz, Khushboo Bhadauria, Mujtaba Nazari, Beatriz Santos,
Anisa Ramos, TaiNing Wang, George K. Thiruvathukal, Konstantin Läufer, Mohammed Abuhamad (Loyola
University Chicago). arXiv:2607.23425, 2026. https://arxiv.org/abs/2607.23425

1,300 real TLA+ specifications, 403 of them with a runnable TLC configuration, used to grade
model-written TLA+ by running it. Its main finding is that "passes the model checker" is not one
number. On the same 300 outputs from leading models:
- **10%** pass TLC;
- **4%** pass while actually exercising behaviour, not sitting in their initial state or checking
  only a type;
- **1.7%** pass with a property that does any work: replacing it with `TRUE` changes the verdict.

**In Anchor:** independent measurement of the gap Anchor's gates are built for, and the case for
reporting a pass only alongside evidence that it tests something. Its proposed next step, mutating
the reference and requiring the check to notice, is what `--mutation-score` does to a policy.

### Agentic Program Verification

Haoxin Tu, Huan Zhao, Yahui Song, Mehtab Zafar, Ruijie Meng, Abhik Roychoudhury (National
University of Singapore). arXiv:2511.17330, 2025. https://arxiv.org/abs/2511.17330

An LLM agent, **AutoRocq**, drives the Rocq (Coq) theorem prover in a loop. It proposes a proof, the
prover answers with context and the reason it failed, and the agent revises. It learns as it goes,
rather than from training on proof corpora.

**In Anchor:** the case for a loop around the checker rather than a single pass. A counterexample
trace, a refusal, or a bound that was too small is exactly the feedback such a loop runs on. It is
also why the loop is code and the model is not (`src/agent/repair.py`).

### Neuro-Formal Verification: Agentic Language-Agnostic Formal Program Reasoning

Shuvendu K. Lahiri (Microsoft Research). arXiv:2608.21516, 2026. https://arxiv.org/abs/2608.21516

An AI agent formalizes a program, its property and its environment into Dafny, and a sound verifier
discharges the result. The stages are "goal-blind": the environment model and preconditions are
frozen before the goal is visible, translation is repaired against a syntax checker only, and every
translated line carries a provenance tag. A bug is reported only with a proof that the
specification fails on a witness, and the pipeline abstains rather than guess. On 206 small Python
programs, half of them buggy, it settles 57% at 92% precision. An LLM judge answers everything at 72%
precision. An unstaged agent-plus-verifier loop "proves" 98% of the buggy programs as well as the
correct ones.

**In Anchor:** the closest published architecture to ours. Several of its safeguards have
counterparts here:
- the drafter of a property module cannot run the scoring gate;
- `--decision-probe` is its reachability check;
- `--mutation-score` scores a claim by the mutants it kills;
- counterexamples are carried back into Dogwood's trace syntax and confirmed by the engine.

It differs where Anchor is weaker: TLC is a bounded checker, where the paper's proof arm is not.

### AxDafny: Agentic Verified Code Generation in Dafny

Benjamin Breen, Austin Letson, Borja Requena Pozo, Leopoldo Sarra (Axiomatic AI). AI for Math
Workshop, ICML 2026. arXiv:2606.32007. https://arxiv.org/abs/2606.32007

An agent that writes Dafny programs and their proofs in a repair loop against the Dafny verifier. It
verifies 92.7% of DafnyBench with Gemini 3.1 Pro. Before the verifier runs, code checks that the
problem's original pre- and postconditions are still present, and rejects the constructs that let a
proof skip the work (`assume`, `{:axiom}`, `{:verify false}`). A second model then looks for subtler
cheats, such as a condition rewritten to be trivially true.

**In Anchor:** the same rule as `src/agent/repair.py`: what a result is checked against is fixed by
code, never chosen by the model. Also a caution for any future Dafny work: verified solutions often
failed the original tests on time limits, because a specification of correctness says nothing about
speed.

### Can Large Language Models Transform Natural Language Intent into Formal Method Postconditions? (nl2postcond)

M. Endres, S. Fakhoury, S. Chakraborty, S. K. Lahiri. FSE 2024. URL: _to add_.
Artifacts: https://github.com/microsoft/intent-formalization/tree/main/nl2postcondition-fse2024

LLM-generated postconditions from docstrings, scored for *soundness* (they hold on the reference
implementation) and *completeness*: the fraction of buggy mutants they catch.

**In Anchor:** the primary source for scoring a claim by the mutants it kills, which is what
`--mutation-score` does to property modules. We mutate the *policy* rather than a program.

### A Benchmark for Vericoding

Sergiu Bursuc, Theodore Ehrenborg, Shaowei Lin, Lacramioara Astefanoaei, Ionel Emilian Chiosa, Jure
Kukovec, Alok Singh, Oliver Butterley, Adem Bizid, Quinn Dougherty, Miranda Zhao, Max Tan, Max
Tegmark. arXiv:2509.22908, 2025. https://arxiv.org/abs/2509.22908

12,504 formal specifications in Dafny, Verus and Lean, with LLMs asked to write code that verifies
against them. Success was 82% in Dafny, 44% in Verus and 27% in Lean. Adding the natural-language
description did not significantly help.

**In Anchor:** a caution about where the difficulty is. If prose adds little once a formal spec
exists, the formal artifact carries the signal and the prose carries the *intent*. A pipeline that
turns prose into a policy and then checks only the policy has checked the easy half. That is the
argument for stating intent separately: as property modules, or as decision tables (`examples/aws1`,
`examples/aws2`, `examples/dogwoodrepo1`).

## TLA+

### Specifying Systems

Leslie Lamport. Addison-Wesley, 2002. Free from the author's site: https://lamport.azurewebsites.net/tla/book.html

The TLA+ reference. Anchor's semantics of Dogwood (`specs/policy/TemporalPolicy/`) and the property
modules are written in it.

### Current Versions of the TLA+ Tools

Leslie Lamport, 2024. The addendum to *Specifying Systems* on where the shipped tools differ from the
book. URL: https://lamport.azurewebsites.net/tla/current-tools.pdf


### Proving Safety Properties

Leslie Lamport, 2019. URL: https://lamport.azurewebsites.net/tla/proving-safety.pdf

Rigorous proofs of safety properties: check an inductive invariant with TLC on a small model, then
prove it with TLAPS for all sizes.

**In Anchor:** the route past TLC's bound, not yet taken. Everything Anchor checks is bounded, and
Lamport's caveat applies to every "within the bound" verdict it prints: a model small enough to check
is often too small to give much confidence.
