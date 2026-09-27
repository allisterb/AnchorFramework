"""Anchor's property-authoring pipeline, as the Strands `Graph` that runs it.

    describe ─┬─> draft ─> preflight ─┬─> score ─┬─> review ─┬─> check ─> answer ─> report
              │                        │          │           │                        ^
              └────────────────────────┴──────────┴───────────┴────────────────────────┘
                     every rejection still reports, and nothing raises

THE SEPARATION IS THE POINT. The agent that DRAFTS the property is not the agent that ANSWERS with
it. Asked to produce both an artifact and its specification, a model finds that a trivial
specification is the cheapest way to pass -- the most-reported pathology in agentic verification,
and the reason this is two agents rather than one with two prompts. `GraphBuilder` enforces it:
one Agent instance cannot be two nodes, and neither sees the other's context.

WHAT IS A MODEL'S DECISION AND WHAT IS NOT. Only `draft`, `review` and `answer` are language models. The five
other nodes are `Computed`: ordinary Python behind the same interface, so the graph is uniform
while the criteria stay in code where nothing can negotiate with them.

  describe   the vocabulary, from the checker  (author.describe)
  draft      MODEL. Proposes a module and a .cfg
  preflight  GATE, static: an invariant the .cfg names but the module never defines, or a claim
             nothing it ranges over can break                            (author.preflight)
  score      GATE, adversarial: does the property hold of every BROKEN version of the policy too?
             If so it constrains nothing                          (author.score, author.assess)
  review     MODEL, a THIRD one, shown ONLY the brief and `explain`'s plain-English reading of
             the claim -- never the formal claim, never the policy. The one gate that compares the
             property against the REQUIREMENT rather than against the policy, and the only one
             with no oracle: it may REJECT, and its agreement is reported as an agreement
  check      the checks actually run             (repair.run_checker, repair.check_property)
  answer     MODEL, a DIFFERENT one. Answers in prose from the verdicts
  report     findings.md, on every path including both rejections

A GATE THAT REJECTS IS NOT A FAILED NODE. It completes, writes its verdict into its own result, and
two `verdict()` edges route on it -- declared as one decision, so the model checker knows exactly
one arm fires. See `annotations.verdict` for why that mattered, and
`tests/strands/anchor_workflow.py` for the four properties this shape was chosen against. The graph
built here is the `gated` variant of that file, which is the point: the shape that was checked and
the object that runs are the same object.

    python src/agent/pipeline.py examples/aws1/07-trust-decay.dw \\
        --intent "After 15 minutes without advisor interaction, the agent loses write access."
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from strands import Agent                                              # noqa: E402
from strands.models import Model                                       # noqa: E402
from strands.multiagent import GraphBuilder                            # noqa: E402
from strands.types.content import Messages                             # noqa: E402
from strands.types.event_loop import Usage                             # noqa: E402
from strands.types.tools import ToolSpec                               # noqa: E402

from annotations import VERDICT_PASS, verdict                          # noqa: E402

from agent import author, policy_agent, repair                         # noqa: E402

STAGES = ("describe", "draft", "preflight", "score", "review", "check", "answer", "report")

# `hitl` adds ONE node, between the last gate a model can pass and the checks themselves: the
# person is shown what the claim forbids and says whether that is what they meant. It sits there
# rather than at the end because a misread requirement confirmed by TLC is still a misread
# requirement, and the reading costs milliseconds while the checks cost minutes. See
# `agent.hitl.stage_confirm`; the graph is otherwise the same shape, and the same properties are
# re-proved over it.
HITL_STAGES = STAGES[:5] + ("confirm",) + STAGES[5:]

# WHAT A MODULE THAT COMPILED AND THEN DIED IS ALMOST ALWAYS DOING, and there are TWO ways to get
# it wrong that are exact opposites -- which is why this said only half of it and the half it said
# was the wrong half for the failure it was attached to. It told a drafter to add tags, three live
# sessions running, while the fault was tags in the one place they must not appear.
TAGGING = (
    "Two ways to get this wrong, and they are opposites.\n\n"
    "INSIDE a field record a value must be TAGGED: write `x <= Num(22)` and `s = Str(\"a1\")`, "
    "never `x <= 22`.\n\n"
    "But a VARIABLE must range over PLAIN values, and you tag it where you USE it:\n"
    "    VARIABLES verified, account\n"
    "    Init == verified \\in {TRUE, FALSE} /\\ account \\in {1, 2}\n"
    "    ... [account |-> Num(account)], [verified |-> Bool(verified)]\n"
    "Never `verified \\in {Bool(TRUE), Bool(FALSE)}`. Tagged values in an `Init` domain are what "
    "produces `Attempted to check equality of integer 1 with non-integer` -- a message that names "
    "neither your variables nor the tagging, and looks like an arithmetic bug rather than a typing "
    "one.")

REVIEWER_PROMPT = (
    "You are given a REQUIREMENT in plain English, and a plain-English reading of a formal claim "
    "somebody wrote to capture it. Your only job is to say whether the second says what the first "
    "says.\n\n"
    "YOU CANNOT SEE THE FORMAL CLAIM ITSELF, and that is deliberate. You are checking a "
    "translation, not reviewing code.\n\n"
    "Answer on the first line with exactly `VERDICT: MATCH` or `VERDICT: MISMATCH`, then say why "
    "in two or three sentences.\n\n"
    "Say MISMATCH when the reading is about a different action, a different direction (permitting "
    "where the requirement forbids, or the reverse), a different threshold or window, or when it "
    "omits a condition the requirement states. Pay attention to WHICH VALUES it says it examines: "
    "a requirement about amounts over $500 that is checked only at $100 and $200 is not that "
    "requirement. Small wording differences are fine; a difference that would let something "
    "through is not.")

ANSWERER_PROMPT = (
    "You report formal verification results to the person who owns the policy. You are given a "
    "property module somebody else drafted, and the verdicts a model checker returned for it.\n\n"
    "Say what was checked, what held, and what did not. Quote the counterexample in the policy "
    "author's own terms -- a request or a session they could try -- never as a TLA+ state.\n\n"
    "You did not write the property and you cannot change it. If the property does not appear to "
    "state what the stated intention meant, say so plainly: that is a finding about the property, "
    "and it is more useful than a verdict about the policy. Do not claim anything was verified "
    "that the verdicts below do not say was verified.\n\n"
    "STATE THE BOUND EVERY TIME, and state it concretely. A property ranges over exactly the "
    "values it names -- the verdicts tell you which, and how many states each claim applies to. "
    "'Holds' means it held over those. Never write 'for all possible requests', 'in every "
    "scenario', 'guaranteed', or 'no situations exist': the check did not establish any of them, "
    "and a reader who believes it will stop looking. Name the values that were checked instead, "
    "and say what was not.")


# ------------------------------------------------------------------------------------------------
# A node that is not a language model
# ------------------------------------------------------------------------------------------------
class Computed(Model):
    """Runs Python and returns its text, behind the `Model` interface a graph node needs.

    A Strands graph node is an `AgentBase` or a nested `MultiAgentBase` and nothing else
    (graph.py:1083), so a deterministic stage has to arrive as one or the other. This is the
    cheaper of the two and it keeps the graph uniform: every node is an Agent, and whether its
    answer came from a model or from a function is a property of the node rather than of the
    wiring.

    It costs nothing and reports nothing: zero tokens, no network, no credentials.
    """

    def __init__(self, run, fn, name: str = "", announce=None) -> None:
        self.run, self.fn, self.name = run, fn, name
        # `announce(stage, seconds)` -- seconds is None when the stage STARTS. Optional and unused
        # by `auto`, which reports when it lands; `hitl` has somebody sitting there, and the wait
        # between `draft` and the first question is minutes of model calls and TLC runs.
        self.announce = announce

    def get_config(self) -> Any:
        return {}

    def update_config(self, **model_config: Any) -> None:
        pass

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("a computed node has no structured output")

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        tool_choice: Any | None = None,
        *,
        system_prompt_content=None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        # NO STAGE MAY RAISE. A node that raises does not merely fail: `_execute_node` re-raises
        # for fail-fast (graph.py:1147), the run ends ABORTED, and `report` never runs -- so there
        # is no findings.md at all, which is the one outcome this pipeline exists to prevent. It
        # is also the hole in `AlwaysReports`, which is stated over `phase = "DONE"` and says
        # nothing about an abort.
        #
        # The property cannot be strengthened to cover ABORTED -- the model lets ANY node fail, so
        # no shape satisfies it. The obligation is therefore discharged HERE, by leaving the
        # executor no exception to see, and what remains is an assumption named in the report: a
        # stage that crashes is a rejection, not an abort.
        started = time.monotonic()
        if self.announce:
            self.announce(self.name, None)
        try:
            text = self.fn(self.run, incoming(messages))
        except Exception as e:                              # noqa: BLE001 - reported, not raised
            self.run.crashed.append(f"{self.name or 'a stage'} failed: {e}")
            text = gate(False, f"{self.name or 'this stage'} could not run: {e}")
        if self.announce:
            # AFTER the except, so a stage that failed is still reported as having finished. A
            # progress line left hanging on the stage that broke reads as "still working".
            self.announce(self.name, time.monotonic() - started)

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": Usage(inputTokens=0, outputTokens=0, totalTokens=0),
                            "metrics": {"latencyMs": 0}}}


def incoming(messages: Messages) -> str:
    """Everything the parents said, as one string.

    `Graph._build_node_input` formats parent results into a text block, so a stage that wants what
    its parent produced reads it here. Most do not -- they read `Run`, because a path or a verdict
    dictionary does not survive a round trip through prose.
    """
    return "\n".join(
        block.get("text", "")
        for m in messages if m.get("role") == "user"
        for block in m.get("content", []) if isinstance(block, dict))


def unframe(text: str) -> str:
    """Just what the parent said, without `_build_node_input`'s scaffolding around it.

    Strands frames a node's input as `Original Task: ...` / `Inputs from previous nodes:` /
    `From <node>:` / `  - Agent: <text>`. Useful to a model, and it was landing verbatim in
    findings.md under a heading that promised the answerer's report.

    This parses another library's PRESENTATION format, which is the kind of thing that breaks
    quietly on an upgrade -- so it falls back to the whole string rather than to an empty one. A
    report with some scaffolding in it is a blemish; a report with nothing in it is a lie.
    """
    marker = "\n  - Agent: "
    if marker not in text:
        return text.strip()

    body = text.rsplit(marker, 1)[1]
    # Continuation lines are indented to match; the first is not, having followed the marker.
    return "\n".join(line[4:] if line.startswith("    ") else line
                     for line in body.splitlines()).strip()


# ------------------------------------------------------------------------------------------------
@dataclass
class Run:
    """What the stages share. The graph gives ordering; this carries the structure."""

    policy: Path
    intent: str
    out: Path
    event_schema: Path | None = None
    module_name: str = "Intent"
    mutants: int = 8
    rounds: int = 3
    max_fields: int | None = None

    round: int = 0
    attempts: list[str] = field(default_factory=list)
    exhausted: bool = False

    # WHAT A PERSON PUT IN, and it is empty in `auto`. `carried` is what the last attempt was told
    # by the gate that rejected it, so a new attempt does not have to rediscover it; the other two
    # are `hitl`'s record of a human in the loop, carried here rather than kept beside it because
    # `report` is the thing that must not be able to omit them. A property shaped by three answers
    # from the person who asked for it is a different artifact from one drafted unattended, and a
    # findings.md that does not say so is overstating what ran.
    carried: str = ""
    clarifications: list[tuple[str, str]] = field(default_factory=list)
    confirmed: bool = False

    # WHAT THE INPUT SCAN SAID, when it said anything. Empty for clean input. Set when a finding
    # was let through -- a medium one always, a high one only under --allow-flagged-input -- because
    # every verdict below was produced by a model that read that text, and a findings.md that does
    # not say so is overstating what ran. See src/checker/scan.py.
    input_scan: str = ""
    input_scan_overridden: bool = False

    decision: str = ""           # varies / constant / skipped, from the decision probe
    review: str = ""             # match / mismatch / no answer / skipped
    review_said: str = ""

    # Per-invocation caps on the agent loop: turns / total_tokens / output_tokens. Empty means no
    # cap. NOT cumulative across calls -- `rounds` rounds of `turns` turns is the product, which is
    # the number to reason about when bounding a run.
    limits: dict[str, int] = field(default_factory=dict)
    capped: list[str] = field(default_factory=list)
    crashed: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    calls: list["Call"] = field(default_factory=list)

    vocab: dict = field(default_factory=dict)
    module: str = ""
    config: str = ""
    module_path: Path | None = None
    complaints: list[str] = field(default_factory=list)
    score: dict = field(default_factory=dict)
    rules: dict = field(default_factory=dict)
    prop: dict = field(default_factory=dict)
    explained: str = ""
    checked: str = ""
    answered: str = ""
    rejected_at: str = ""
    findings: Path | None = None


@dataclass
class Call:
    """One model call, and what it cost."""

    who: str
    input: int = 0
    output: int = 0
    total: int = 0
    # HOW MUCH OF `input` THE PROVIDER SERVED FROM ITS PROMPT CACHE. Kept because without it the
    # table cannot tell an expensive round from a cheap one: a retry re-sends the whole prior
    # exchange, and whether that is billed in full or at a cache discount is the difference between
    # those two readings of the same `input` figure.
    cached: int = 0
    seconds: float = 0.0
    capped: bool = False


def spent(result) -> tuple[int, int, int, int]:
    """This call's tokens -- NOT the agent's running total.

    `metrics.accumulated_usage` is cumulative across every invocation of the same Agent object, so
    reading it per call bills round 1 again on round 2 and the first two again on round 3. The
    drafter is reused across rounds, so that error would be silent and would grow. The per-call
    figure is `agent_invocations[-1].usage`; this is the same trap recorded in
    tests/strands/shared_budget.py, met again in a different place.
    """
    m = getattr(result, "metrics", None)
    invocations = getattr(m, "agent_invocations", None) if m else None
    usage = invocations[-1].usage if invocations else getattr(m, "accumulated_usage", None)
    if not usage:
        return 0, 0, 0, 0
    # `cacheReadInputTokens` is how many of the input tokens the provider served from its prompt
    # cache. Strands maps it from Gemini's `cached_content_token_count` (models/gemini.py:504) and
    # from the equivalent on Bedrock and Anthropic; a provider that reports nothing leaves it absent
    # rather than zero, which is a different statement and is why the default is used rather than
    # assumed.
    return (usage.get("inputTokens", 0), usage.get("outputTokens", 0),
            usage.get("totalTokens", 0), usage.get("cacheReadInputTokens", 0))


def ask(agent, prompt: str, run: Run, who: str) -> tuple[str, bool]:
    """Call an agent under the run's caps. Returns (what it said, whether a cap cut it off).

    A TRIPPED CAP IS NOT AN ERROR AND DOES NOT LOOK LIKE ONE. Strands reports it as a stop_reason
    -- `limit_turns`, `limit_total_tokens`, `limit_output_tokens` -- and the agent returns
    normally, so `Graph` marks the node COMPLETED (it maps only "interrupt" to anything else).
    A capped agent is therefore indistinguishable from a finished one unless somebody looks, and
    what it returns is a truncated answer. Here somebody looks.
    """
    started = time.monotonic()
    try:
        result = agent(prompt, **({"limits": run.limits} if run.limits else {}))
    except Exception as e:                                  # noqa: BLE001 - reported, not raised
        # THE MODEL COULD NOT BE REACHED, which is NOT a defect in Anchor -- a wrong model id, a
        # missing key, a region that does not carry the model, a quota. Caught here rather than by
        # the stage's generic handler because that one says "a stage of Anchor itself failed" and
        # sends the reader to the wrong place: a run with `--llm gemini-3.7-flash` reported five
        # Anchor bugs for what was a 404 on the model name.
        run.unreachable.append(f"{who}: {e}")
        run.calls.append(Call(who, seconds=time.monotonic() - started, capped=True))
        return "", True
    elapsed = time.monotonic() - started

    tokens = spent(result)
    stop = str(getattr(result, "stop_reason", "") or "")
    cut = stop.startswith("limit_")
    run.calls.append(Call(who, *tokens, seconds=elapsed, capped=cut))
    if cut:
        run.capped.append(f"{who} was cut off by the {stop} cap")
    return str(result).strip(), cut


def gate(ok: bool, said: str) -> str:
    """A gate's own account of what it decided, in the form `verdict()` reads."""
    return f"{VERDICT_PASS}\n{said}" if ok else f"ANCHOR-VERDICT: REJECT\n{said}"


# ------------------------------------------------------------------------------------------------
# The stages
# ------------------------------------------------------------------------------------------------
def stage_describe(run: Run, _: str) -> str:
    """The vocabulary, and the request built from it. Not guessed and not asked of the model."""
    run.vocab = author.describe(run.policy, run.event_schema, max_fields=run.max_fields)
    if run.vocab.get("_failed"):
        # A GATE, not an exception. An unreadable policy is an ordinary outcome -- a wrong path, a
        # syntax error, a schema that will not load -- and raising here would abort the run and
        # produce no findings.md, which is a worse answer than saying what went wrong.
        run.rejected_at = "describe"
        run.complaints = [f"{run.policy.name} could not be read: {run.vocab.get('_why')}"]
        return gate(False, run.complaints[0])

    run.vocab["requiredModuleName"] = run.module_name
    actions = len(run.vocab.get("actions") or [])
    return gate(True, f"read {run.policy.name}: {actions} action(s), and a vocabulary the module "
                      f"may name")


def stage_draft(run: Run, asked: str, drafter) -> str:
    """Propose a module, and try again when it will not compile or says nothing.

    THE RETRY IS HERE AND NOT IN THE GRAPH, deliberately. A retry is a cycle, and neither model
    can express one: `oracle` is chosen in Init and never changes, so a retry edge cannot say
    "again, then stop", and StrandsGraph's StartBatch increments `runs` with no guard, so a cycle
    breaks TypeOK's `runs \\in 0..MaxRuns`. A cyclic graph here would be a graph nothing checks.
    Keeping the loop inside one node keeps the whole shape acyclic and every property we proved
    about it true -- at the price that these rounds are invisible to the model, which is a real
    limitation and is stated rather than hidden.

    ONLY THE CHEAP GATES ARE IN THE LOOP: SANY (~1s) and `preflight` (milliseconds). `score` runs
    TLC once per mutant and stays outside, one shot -- a rejection there ends the run with a
    report, which is what `AlwaysReports` guarantees.
    """
    run.out.mkdir(parents=True, exist_ok=True)
    scratch = run.out / f"{run.module_name}.tla"

    # Empty in `auto`. In `hitl` this is what the PREVIOUS pass was rejected for, so round 1 of a
    # new pass starts where the last one left off instead of repeating its mistake and spending a
    # round being told about it again.
    feedback = run.carried
    for attempt in range(1, max(1, run.rounds) + 1):
        run.round = attempt
        # BUILT FROM THE VOCABULARY, never from what the parent node said. `describe` emits a
        # verdict now, and a prompt assembled out of another node's framed output would carry that
        # marker into the model's instructions.
        #
        # AND ONLY ONCE. The manual is 15 KB and the vocabulary another 8, and the SAME agent runs
        # every round -- so a later round built from `draft_prompt` pays for the whole first
        # exchange and then for a second copy of text already in front of the model. Measured on a
        # live run: round 2's input was 19,501 tokens, of which 6,522 was exactly that. Later
        # rounds send the feedback alone and let the conversation carry the rest.
        prompt = (author.draft_prompt(run.vocab, run.intent, feedback) if attempt == 1
                  else author.retry_prompt(feedback))
        text, cut = ask(drafter, prompt, run, f"draft round {attempt}")
        module, config = author.parse_draft(text)
        run.attempts.append(text)

        # A CAPPED DRAFT IS A FAILED ROUND, not a draft. Left alone it would reach the gates as a
        # half-written module, be rejected for not compiling, and the report would blame the model
        # for a syntax error that was really a budget running out.
        # No point spending the allowance on an endpoint that is not answering.
        if run.unreachable:
            run.rejected_at = "draft"
            run.complaints = ["the model could not be reached: "
                              + "; ".join(run.unreachable)[-600:]]
            return ""

        if cut:
            feedback = ("Your reply was cut off before it finished -- a budget cap was reached. "
                        "Return the two files and nothing else: no commentary, no explanation, "
                        "and keep the comments in the module short.")
            continue

        if not module.strip() or not config.strip():
            feedback = ("Your reply did not contain both files. Return the module between "
                        "===MODULE=== and ===CONFIG===, and the .cfg after ===CONFIG===.")
            continue

        # DOES IT COMPILE? The failure a live run actually hit, and the cheapest to fix: SANY
        # names the line, the column and the token, and one more round is seconds.
        scratch.write_text(module, encoding="utf-8")
        scratch.with_suffix(".cfg").write_text(config, encoding="utf-8")
        ok, out = author.compiles(run.policy, scratch, event_schema=run.event_schema,
                                  max_fields=run.max_fields)
        if not ok:
            feedback = ("Your module did not compile. Fix exactly this and return the whole "
                        f"module again:\n\n{out[:2000]}")
            continue

        # AND DOES IT SAY ANYTHING? Free, and it is the other way a draft comes back useless.
        try:
            said = author.preflight(module, config, run.module_name)
        except Exception as e:                              # noqa: BLE001 - fed back, not raised
            feedback = f"Your module could not be read: {e}"
            continue
        if said:
            feedback = "Your draft was rejected:\n\n" + "\n".join(said) + "\n\nTry again."
            continue

        # AND DOES THE POLICY EVER ANSWER DIFFERENTLY? Seconds, and it is the defect the whole
        # aws2 sweep produced: five properties whose claims were well formed and whose policy
        # refused every request they named, so each held without testing anything. Caught here it
        # is a round of feedback; caught by mutation scoring it is a TLC run per mutant and a
        # complaint that describes the symptom.
        verdict, why = author.decides(run.policy, scratch, event_schema=run.event_schema,
                                      max_fields=run.max_fields)
        run.decision = verdict
        if verdict == "error":
            # The module compiled and then died computing a decision. Cheap to find here, and the
            # difference between one round of feedback and the whole allowance spent producing a
            # diagnostic nobody read.
            feedback = ("Your module compiled but could not be evaluated:\n\n" + why[-1500:]
                        + "\n\n" + TAGGING)
            continue

        # AND DO THE CLAIMS THEMSELVES EVALUATE? The probe only exercises the decision term, and
        # an arithmetic comparison inside a claim -- `amount <= 2500` where amount is `Num(...)` --
        # dies somewhere the probe never reaches. ONE TLC run, against the nine that `score` would
        # spend to report the same thing as "the module produced no verdict".
        once = repair.check_property(run.policy, scratch, event_schema=run.event_schema,
                                     max_fields=run.max_fields)
        if once.get("_failed"):
            feedback = ("Your module compiled, but checking it produced no verdict:\n\n"
                        + str(once.get("_why"))[-1500:]
                        + "\n\n" + TAGGING)
            continue

        if verdict == "constant":
            feedback = ("Your property cannot be tested against this policy:\n\n"
                        + why[-1500:] + "\n\nGive the module states the policy answers "
                        "differently -- if a request needs a prior verification, approval or "
                        "read, put that event in the session before the one you are deciding.")
            continue

        return text                                          # the gate nodes still judge it

    # Rounds exhausted. The last attempt is passed on ANYWAY rather than raising: the gates below
    # are what refuse a draft, and `report` is downstream of them. A node that raised here would
    # fail-fast the run and produce no findings.md at all -- the one outcome this shape exists to
    # prevent.
    run.exhausted = True
    return run.attempts[-1] if run.attempts else ""


def stage_preflight(run: Run, said: str) -> str:
    """The static gate. Milliseconds, against minutes for the one below it."""
    run.module, run.config = author.parse_draft(said)
    if not run.module.strip() or not run.config.strip():
        run.rejected_at = "preflight"
        run.complaints = ["the draft did not contain both a module and a .cfg between the "
                          "===MODULE=== and ===CONFIG=== markers"]
        return gate(False, run.complaints[0])

    try:
        run.complaints = author.preflight(run.module, run.config, run.module_name)
        # WHAT THE CLAIM FORBIDS, AND OVER HOW MANY STATES. Read here because the module is
        # already in hand and it costs milliseconds -- and carried all the way to `answer`,
        # because it is the only thing in the whole run that states the BOUND. Without it the
        # reporter is handed "the property HOLDS" and nothing to stop it writing "for all
        # possible requests", which is what it did.
        from checker.explain import Module, explain, render             # noqa: PLC0415
        run.explained = render(explain(Module(run.module, run.config, run.module_name)))
    except Exception as e:                                  # noqa: BLE001 - reported, not raised
        # A draft that will not even parse is a rejection, not a crash of the pipeline. The gate
        # has done its job; `report` still runs and says so.
        run.complaints = [f"the module could not be read: {e}"]

    if run.complaints:
        run.rejected_at = "preflight"
        return gate(False, "\n".join(run.complaints))
    return gate(True, "nothing statically wrong: every named invariant is defined, and each "
                      "claim ranges over states that can break it")


def stage_score(run: Run, _: str) -> str:
    """The adversarial gate: does this property notice the policy breaking?"""
    run.out.mkdir(parents=True, exist_ok=True)
    run.module_path = run.out / f"{run.module_name}.tla"
    run.module_path.write_text(run.module, encoding="utf-8")
    run.module_path.with_suffix(".cfg").write_text(run.config, encoding="utf-8")

    run.score = author.score(run.policy, run.module_path, event_schema=run.event_schema,
                             max_fields=run.max_fields, mutants=run.mutants)
    run.complaints = author.assess(run.score, run.config)
    if run.complaints:
        run.rejected_at = "score"
        return gate(False, "\n".join(run.complaints))

    caught = run.score.get("caught")
    return gate(True, f"the property discriminates: it caught {caught} of the broken versions of "
                      f"this policy that were tried")


def stage_review(run: Run, _: str, reviewer) -> str:
    """Does the property say what the BRIEF said? A third agent, shown only the two English texts.

    THE ONE THING NO OTHER GATE ASKS. Every check before this one compares the property against the
    POLICY -- does it compile, does it evaluate, does the decision vary, does it catch a mutant.
    None of them compares it against the REQUIREMENT, so a property can pass all of them and be
    about the wrong rule entirely.

    BLINKERED ON PURPOSE. The reviewer gets the brief and `explain`'s reading of the claim, and
    never the TLA+ or the policy. Shown the module it would re-read the drafter's reasoning and
    agree with it, which is the same self-certification the drafter/answerer split exists to stop.

    AND IT CANNOT CERTIFY, ONLY REJECT. Every other gate is a criterion in code with an exact
    answer; this one is a model's judgement, with no oracle behind it. So a MISMATCH stops the run
    and a MATCH is reported as an agreement rather than a verification -- and an answer that comes
    back in no recognisable form is treated as NOT REJECTED rather than as a failure, because
    blocking on it would give this gate an authority it does not have.
    """
    if not run.explained.strip():
        run.review = "skipped"
        return gate(True, "no plain-English reading was available to review")

    asked = (f"THE REQUIREMENT:\n\n{run.intent}\n\n"
             f"THE READING OF THE FORMAL CLAIM WRITTEN TO CAPTURE IT:\n\n{run.explained}")
    said, cut = ask(reviewer, asked, run, "the review")

    verdict = "mismatch" if "MISMATCH" in said.upper() else (
        "match" if "MATCH" in said.upper() else "no answer")
    run.review, run.review_said = verdict, said

    if verdict == "mismatch":
        run.rejected_at = "review"
        run.complaints = [f"a second model, shown only the requirement and the plain-English "
                          f"reading of the claim, judged that they do not match:\n\n{said}"]
        return gate(False, said)

    if verdict == "no answer" or cut:
        return gate(True, "the reviewer did not answer in the required form, so the round trip "
                          "was NOT established; nothing was rejected on that basis")
    return gate(True, said)


def stage_check(run: Run, _: str) -> str:
    """The checks, run. Two invocations because `--property` REPLACES the derived questions."""
    # THE DERIVED QUESTIONS GET NO --max-fields, deliberately. They quantify over the product of
    # every field domain, so above the checker's own limit they do not finish -- measured at 7
    # minutes and still running on agent-policy.dw. Left at the default they REFUSE in about a
    # second, with the reason, which is the honest answer and the cheap one. The property run
    # below takes the raised limit, because a property module states its OWN request set and is
    # therefore not subject to that product at all: the same policy answers it in 3 seconds.
    run.rules = repair.run_checker(run.policy, event_schema=run.event_schema)
    run.prop = repair.check_property(run.policy, run.module_path, event_schema=run.event_schema,
                                     max_fields=run.max_fields)

    lines = [f"Policy: {run.policy.name}", f"Property: {run.module_name}", ""]
    if run.prop.get("_failed"):
        lines.append(f"The property could not be checked: {run.prop.get('_why')}")
    else:
        lines.append("The stated property HOLDS." if run.prop.get("held")
                     else "The stated property is BROKEN.")
        for v in run.prop.get("violations") or []:
            lines.append(f"  {v['invariant']} is violated at {v['state']}")

    # THE BOUND, in the same breath as the verdict. "Holds" on its own is the most overclaimable
    # sentence this pipeline produces: a property ranges over exactly what it names, and nothing
    # in a TLC verdict says how little that might be.
    lines += ["", "WHAT WAS ACTUALLY CHECKED -- each claim, what it forbids, and how many of the "
              "states it ranges over its condition applies to:", "", run.explained.strip(), "",
              "This says nothing about requests the property does not name."]

    if run.rules.get("_failed"):
        lines += ["", "The derived questions were NOT attempted: this policy is outside the "
                  "subset they can range over.", f"  {str(run.rules.get('_why'))[-300:]}",
                  "That is a limit of those questions, not a verdict about the policy."]
    else:
        # THE FIELDS ARE `verdict` AND `defects`. This read `finding` and `rule`, neither of which
        # the checker emits, so every report said "Derived findings: 0" whatever was found -- a
        # silent zero, which is the worst possible way for a verification tool to be wrong.
        defects = set(run.rules.get("defects") or [])
        found = [r for r in (run.rules.get("rules") or []) if r.get("index") in defects]
        lines += ["", f"Derived findings: {len(found)}"]
        lines += [f"  rule {r.get('index')} ({r.get('effect')}): {r.get('verdict')}"
                  f" -- {r.get('note')}" for r in found]
        if run.rules.get("unknown"):
            lines.append(f"  {len(run.rules['unknown'])} rule(s) returned no verdict")
    run.checked = "\n".join(lines)
    return run.checked


def stage_answer(run: Run, said: str, answerer) -> str:
    """The reporter, called by us rather than by the graph, so that a cap can be put on it.

    `Limits` is a per-call argument on `__call__` / `invoke_async` / `stream_async` and is not
    available on the constructor, and `Graph` invokes a node executor itself with no way to pass
    one. An agent that is a node is therefore an agent nobody can bound -- so this one is wrapped,
    as `draft` is.
    """
    run.answered, cut = ask(answerer, unframe(said), run, "the report")
    if cut:
        # Said in the findings rather than only in `run.capped`: a truncated report that does not
        # say it was truncated reads as a complete one, and the reader cannot tell.
        run.answered += ("\n\n**This report was cut off by a budget cap and is incomplete.** The "
                         "verdicts above are the record; this prose is not all of it.")
    return run.answered


def stage_report(run: Run, said: str) -> str:
    """findings.md, on every path -- including both rejections.

    Reached from three places and it has to read as one document from any of them, which is why it
    consults `Run` rather than whatever its parent happened to say.
    """
    run.out.mkdir(parents=True, exist_ok=True)
    run.findings = run.out / "findings.md"

    lines = [f"# {run.policy.name}", "", f"**Stated intention.** {run.intent}", ""]
    # THE INPUT SCAN, before anything a model produced -- because what it found is text the model
    # read, and every verdict below is read differently if that text was an instruction to it.
    if run.input_scan:
        lines += ([f"> **The input scan flagged this policy's inputs, and they were shown to the "
                   f"model anyway (`--allow-flagged-input`):** {run.input_scan}. Every result below "
                   f"was produced by a model that read that text. Run `anchor scan` for the "
                   f"findings.", ""]
                  if run.input_scan_overridden else
                  [f"**Input scan.** {run.input_scan} -- nothing high enough to refuse on; run "
                   f"`anchor scan` for what was found.", ""])
    # WHAT A PERSON PUT IN, before any verdict. Every claim below is read differently depending on
    # whether the requirement arrived whole or was assembled over four rounds of being told what
    # was wrong with the last one -- and only this section can tell the two apart. In `auto` it is
    # empty and nothing is printed.
    if run.clarifications:
        lines += [f"**A person was asked about this requirement {len(run.clarifications)} "
                  f"time(s), and the answers are part of it:**", ""]
        lines += [f"- *{q}* — {a}" for q, a in run.clarifications]
        lines += [""]
    # A CRASHED STAGE FIRST OF ALL. It is caught rather than raised so that this file exists at
    # all -- an exception would abort the run and write nothing -- but it is a defect in Anchor,
    # not a finding about the policy, and must not be read as one.
    if run.unreachable:
        lines += ["> **The model could not be reached, so nothing was drafted or checked.**",
                  "> This is a configuration problem -- a model id, a key, a region, a quota --",
                  "> not a defect in Anchor and not a finding about your policy.", ">"]
        lines += [f"> - {u}" for u in run.unreachable]
        lines += [""]

    if run.crashed:
        lines += ["> **A stage of Anchor itself failed during this run.** This is a bug in Anchor,",
                  "> not a finding about your policy, and whatever appears below is incomplete.",
                  ">"]
        lines += [f"> - {c}" for c in run.crashed]
        lines += [""]

    # BUDGET CAPS NEXT, because every verdict below is read differently if one fired. A capped
    # run is not a shorter run: it is one whose agent was interrupted mid-sentence.
    if run.capped:
        lines += ["> **A budget cap fired during this run.**", ">"]
        lines += [f"> - {c}" for c in run.capped]
        lines += [">", "> Raise `--turns` / `--total-tokens` / `--output-tokens`, or narrow the "
                  "intention, and run it again.", ""]
    if run.round > 1 or run.exhausted:
        lines += [f"*Drafted in {run.round} of {run.rounds} attempt(s)"
                  + (", and the allowance ran out -- what follows is the last attempt, judged by "
                     "the same gates as any other." if run.exhausted else ".") + "*", ""]
    if run.rejected_at:
        # WHOSE JUDGEMENT STOPPED IT. Six of the gates are criteria in code with exact answers,
        # `review` is a model's opinion, and `confirm` is the person's -- and a reader deciding
        # whether to argue with the verdict needs to know which of the three they are arguing with.
        # Said generically, this line claimed all three were code.
        whose = {"review": "The gate below is a second model's judgement about whether the claim "
                           "says what the requirement says. It has no oracle behind it, and it is "
                           "the one gate here a person may overrule.",
                 "confirm": "The gate below is the PERSON'S: they were shown, in plain English, "
                            "what the claim forbids, and said it is not what they meant. No tool "
                            "disagreed with the draft."}.get(
            run.rejected_at,
            "The gate below is a criterion in code, not a judgement a model was asked to make.")
        lines += [f"## No property was checked: the draft was rejected at `{run.rejected_at}`", "",
                  f"{whose} Nothing downstream ran, and nothing here was verified.", ""]
        lines += [f"- {c}" for c in run.complaints]
    else:
        # `said` is what the ANSWERER said -- report's parent on this path. The verdicts it was
        # answering from are read off Run, because they are the record and its prose is not.
        # `stage_answer` already set this from the agent's own reply. The fallback is defensive:
        # an empty report section would be worse than one with some scaffolding in it.
        run.answered = run.answered or unframe(said)
        # WHY IT WAS KEPT, and there are two different reasons. Mutation scoring is skipped when
        # the property already FAILS on the policy as written -- it has shown it discriminates by
        # failing, so there is nothing to score. Printing `caught None` there read as a property
        # kept for catching nothing, which is the opposite of what happened.
        caught = run.score.get("caught")
        why = (f"kept because it caught {caught} broken version(s) of this policy"
               if caught is not None else
               "kept because it does not hold on the policy as written -- it has already shown "
               "it can tell one policy from another, so it was not scored against mutants")
        # WHAT THE ROUND TRIP ESTABLISHED, and it is deliberately modest. Every other line in this
        # report rests on a criterion in code; this one rests on a model agreeing with another
        # model, so it is reported as an agreement and never as a verification.
        trip = {
            "match": "A second model, shown only the requirement and the plain-English reading of "
                     "the claim — never the formal claim itself — judged that they match. That is "
                     "an agreement between two models, not a proof that the claim captures the "
                     "requirement.",
            "no answer": "The round trip was **not established**: the reviewing model did not "
                         "answer in the required form. Nothing was rejected on that basis, and "
                         "nothing was confirmed either.",
            "skipped": "The round trip was not attempted.",
        }.get(run.review, "")

        lines += ["## What was checked", "", f"`{run.module_name}.tla`, drafted from the "
                  f"intention above and {why}.", ""]
        if trip or run.confirmed:
            lines += ["### Does it say what you asked for?", ""]
            # THE PERSON FIRST, because their answer is the better evidence and because putting the
            # two models' agreement above it would read as the stronger finding. Still stated
            # exactly: they read a plain-English reading of the claim, not the claim.
            if run.confirmed:
                lines += ["**A person was shown, in plain English, what this claim forbids, and "
                          "confirmed it is what they meant — before anything was checked.** They "
                          "did not read the formal claim, so what they confirmed is the reading "
                          "of it; the two are generated from the same module and the reading is "
                          "the part a person can audit.", ""]
            if trip:
                lines += [trip, ""]
        lines += ["## Verdicts", "", "```", run.checked.strip(), "```", "",
                  "## Reported", "", run.answered]

    # AND WHAT THIS DOCUMENT IS ALLOWED TO CLAIM. Both readings end in the same place -- nobody
    # wrote the property -- but a run a person steered is not an unattended one, and a footer that
    # said so either way would be wrong in one of the two directions every time.
    lines += ["", "---", "",
              "*A property drafted by a model and gated by Anchor. A person stated the requirement "
              "and confirmed a plain-English reading of the claim, which is better evidence than "
              "an unattended run and is still not a person having written the property.*"
              if run.confirmed else
              "*A property drafted by a model and gated by Anchor. Findings against an "
              "agent-authored property are weaker evidence than findings against one a person "
              "wrote.*", ""]

    run.findings.write_text("\n".join(lines), encoding="utf-8")
    return f"wrote {run.findings}"


def usage(run: Run, result) -> str:
    """What the run cost, in tokens and in seconds.

    APPENDED AFTER THE GRAPH FINISHES rather than written by `report`, because the node timings
    only exist once every node has run -- and `report` is a node.

    THE GRAPH'S OWN TOTALS ARE NOT USED, and cannot be. Every stage here is an Agent whose model is
    `Computed`, which reports zero tokens because it makes no model call; the two real calls happen
    INSIDE those nodes, through `ask`. So `result.accumulated_usage` is zero for this pipeline and
    reading it would report a run that cost nothing. The per-call figures are the record.
    """
    lines = ["", "## What this run cost", "",
             "| | tokens in | of which cached | out | total | seconds |",
             "|---|---:|---:|---:|---:|---:|"]
    for c in run.calls:
        lines.append(f"| {c.who}{' (cut off)' if c.capped else ''} | {c.input:,} | {c.cached:,} "
                     f"| {c.output:,} | {c.total:,} | {c.seconds:.1f} |")

    tin = sum(c.input for c in run.calls)
    tcached = sum(c.cached for c in run.calls)
    tout = sum(c.output for c in run.calls)
    ttot = sum(c.total for c in run.calls)
    tsec = sum(c.seconds for c in run.calls)
    lines.append(f"| **{len(run.calls)} model call(s)** | **{tin:,}** | **{tcached:,}** "
                 f"| **{tout:,}** | **{ttot:,}** | **{tsec:.1f}** |")

    # SAID PLAINLY, because a column of zeros is ambiguous on its own -- it reads equally as "the
    # provider has no cache" and as "the prefix changed every round". Neither is good news, and a
    # reader deciding whether a retry is cheap needs to know which it is looking at.
    if run.calls and not tcached:
        lines += ["", "*None of that input was served from a prompt cache.* A retry re-sends the "
                  "whole prior exchange, so whether that is billed in full is the difference "
                  "between a cheap round and an expensive one. Gemini caches implicitly on a "
                  "matching PREFIX; Strands cannot place an explicit cache point there, because "
                  "its Gemini provider skips `cachePoint` blocks (models/gemini.py:251)."]

    order = getattr(result, "execution_order", None) or []
    if order:
        lines += ["", "Time per stage, model calls and verification together:", "", "```"]
        for node in order:
            ms = getattr(node, "execution_time", 0) or 0
            lines.append(f"  {node.node_id:<12} {ms / 1000:8.1f}s")
        total_ms = getattr(result, "execution_time", 0) or 0
        lines.append(f"  {'total':<12} {total_ms / 1000:8.1f}s")
        lines.append("```")
        # The gap between the two totals is TLC, which is most of the wall clock on any real
        # policy and costs no tokens at all. Worth saying, or the token figure reads as the price
        # of the run rather than as the price of the two model calls in it.
        lines += ["", f"Of which {tsec:.1f}s was model calls; the rest is verification -- TLC "
                  f"runs in `score` and `check`, which cost no tokens."]

    return "\n".join(lines) + "\n"


def append_usage(run: Run, result) -> None:
    """Add the cost section to findings.md. Safe to call when there is no findings.md."""
    if run.findings and run.findings.exists():
        run.findings.write_text(run.findings.read_text(encoding="utf-8").rstrip() + "\n"
                                + usage(run, result), encoding="utf-8")


# ------------------------------------------------------------------------------------------------
def computed(run: Run, fn, name: str, announce=None) -> Agent:
    return Agent(model=Computed(run, fn, name, announce), callback_handler=None, name=name)


def build(run: Run, drafter: Agent | None = None, answerer: Agent | None = None,
          reviewer: Agent | None = None, *, provider: str = "auto", model: str | None = None,
          max_node_executions: int | None = None, node_timeout: float | None = None,
          confirm=None, announce=None):
    """The graph. `gated` from tests/strands/anchor_workflow.py, wired to the real stages.

    The two agents are injected so the pipeline can be exercised without a provider -- and so that
    they are visibly two objects. `GraphBuilder` refuses one instance as two nodes, which is the
    separation enforced rather than intended.

    `confirm` is `hitl`'s one extra gate, `fn(run, text) -> str` returning a `gate()` verdict, and
    it goes between `review` and `check`. Optional and absent by default, so `auto` builds exactly
    the graph it always did -- an extra node would change the shape that
    `tests/strands/anchor_workflow.py` chose, and the whole point of that exercise is that the
    shape which runs is the shape that was checked. With it the graph is the SAME SHAPE with one
    more gate on the same pattern, and `AlwaysReports` is re-proved over it rather than assumed.
    """
    if drafter is None or answerer is None or reviewer is None:
        from agent.policy_agent import build_model as _build           # noqa: PLC0415

        def build_model():
            return _build(provider, model)

        # TWO models, deliberately built twice. Sharing one object would share whatever state it
        # carries, and the separation this graph exists for is about what the answerer has seen.
        # THE DRAFTER IS THE ONLY ONE WITH TOOLS, and they are the mechanical checks only --
        # compile, evaluate, read back, evaluate an expression. Not mutation scoring, and not the
        # reviewer: a model that can see the gate that judges it will tune the property until it
        # passes, which is the pathology the whole shape exists to prevent. See `agent.drafting`.
        from agent.drafting import tools as drafting_tools               # noqa: PLC0415

        drafter = drafter or Agent(model=build_model(), callback_handler=None,
                                   system_prompt=author.DRAFTER_PROMPT, name="draft",
                                   tools=drafting_tools(run))
        answerer = answerer or Agent(model=build_model(), callback_handler=None,
                                     system_prompt=ANSWERER_PROMPT, name="answer")
        reviewer = reviewer or Agent(model=build_model(), callback_handler=None,
                                     system_prompt=REVIEWER_PROMPT, name="review")

    describe_ok, describe_no = verdict("describe")
    preflight_ok, preflight_no = verdict("preflight")
    review_ok, review_no = verdict("review")
    score_ok, score_no = verdict("score")

    # THE SEPARATION, asserted here because the graph no longer gets it free. While `draft` was
    # the drafting Agent itself, GraphBuilder refused one instance as two nodes; now that the
    # retry loop wraps it, the drafter is not a node and nobody else is checking.
    if drafter is answerer or drafter is reviewer or answerer is reviewer:
        raise ValueError("the agent that drafts the property cannot be the agent that reports on "
                         "it: asked for both, a model finds a trivial property the cheapest way "
                         "to pass, and a reporter that wrote the claim is not reviewing it")

    b = GraphBuilder()
    # A BACKSTOP, and it must never be what stops this run. Hitting it is not a graceful finish:
    # the executor sets status FAILED and returns from the batch loop (graph.py:787), so `report`
    # never runs and there is no findings.md -- the precise outcome `AlwaysReports` exists to
    # forbid. So the cap is set above what the graph can possibly use, and the thing that actually
    # bounds the work is `rounds`, inside `draft`, where running out still routes to `report`.
    #
    # Deliberately NOT set_execution_timeout: the `score` gate runs TLC once per mutant, and a
    # wall-clock bound would turn a slow-but-correct check into a stopped run with no report, for
    # the same reason. `author.score` carries its own timeout, where what is being timed is known.
    b.set_max_node_executions(max_node_executions or len(HITL_STAGES) * 2)
    if node_timeout is not None:
        b.set_node_timeout(node_timeout)

    b.add_node(computed(run, stage_describe, "describe", announce), "describe")
    b.add_node(computed(run, lambda r, t: stage_draft(r, t, drafter), "draft", announce), "draft")
    b.add_node(computed(run, stage_preflight, "preflight", announce), "preflight")
    b.add_node(computed(run, stage_score, "score", announce), "score")
    b.add_node(computed(run, lambda r, t: stage_review(r, t, reviewer), "review", announce), "review")
    b.add_node(computed(run, stage_check, "check", announce), "check")
    b.add_node(computed(run, lambda r, t: stage_answer(r, t, answerer), "answer", announce), "answer")
    b.add_node(computed(run, stage_report, "report", announce), "report")

    b.add_edge("describe", "draft", condition=describe_ok)
    b.add_edge("describe", "report", condition=describe_no)
    b.add_edge("draft", "preflight")
    b.add_edge("preflight", "score", condition=preflight_ok)
    b.add_edge("preflight", "report", condition=preflight_no)
    b.add_edge("score", "review", condition=score_ok)
    b.add_edge("score", "report", condition=score_no)
    b.add_edge("review", "report", condition=review_no)
    if confirm is None:
        b.add_edge("review", "check", condition=review_ok)
    else:
        # ONE MORE GATE ON THE SAME PATTERN, which is why it costs nothing to reason about: a
        # `verdict()` pair like the other four, one arm to the work and one arm to the report, and
        # no new edge into anything that did not already have one.
        confirm_ok, confirm_no = verdict("confirm")
        b.add_node(computed(run, confirm, "confirm", announce), "confirm")
        b.add_edge("review", "confirm", condition=review_ok)
        b.add_edge("confirm", "check", condition=confirm_ok)
        b.add_edge("confirm", "report", condition=confirm_no)
    b.add_edge("check", "answer")
    b.add_edge("answer", "report")
    b.set_entry_point("describe")
    return b.build()


# ------------------------------------------------------------------------------------------------
# A directory of policies
# ------------------------------------------------------------------------------------------------
INTENT_HEADING = re.compile(r"^##\s+(\S+)\s*$")


def module_name_for(label: str) -> str:
    """A TLA+ module name from an intent's heading.

    TLA+ requires the module name to match its file name, and this loop chooses the file name, so
    the name has to be derived rather than asked for. Identifiers here may not carry `-` or `.` or
    lead with a digit -- and every requirement label in `examples/` does at least one of those.
    """
    parts = re.split(r"[^A-Za-z0-9]+", label.removesuffix(".dw"))
    name = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return name if name[:1].isalpha() else f"Intent{name}"


def read_intents(path: Path) -> dict[str, str]:
    """`## <policy>.dw` followed by the requirement, as blockquote or prose.

    A FILE OF ITS OWN, and not a field in the policy. The intent has to come from somewhere the
    policy did not write, or the property drafted from it restates the rules and passes whatever
    they say. Keeping it in a separate file is the cheapest way to make that visible -- and it is
    checkable, because each entry is also quoted in its policy's header comment.
    """
    out: dict[str, str] = {}
    name, body = "", []
    for line in path.read_text(encoding="utf-8").splitlines():
        if (m := INTENT_HEADING.match(line)):
            if name and body:
                out[name] = " ".join(body).strip()
            name, body = m.group(1), []
        elif name and line.strip() and not line.startswith("#"):
            body.append(line.lstrip("> ").strip())
    if name and body:
        out[name] = " ".join(body).strip()
    return out


def intent_for(stated: dict[str, str], what: str) -> str | None:
    """One heading's requirement, matched the way somebody types a filename.

    Case-insensitive and the `.dw` optional, because `07-trust-decay` and `07-Trust-Decay.dw` are
    the same thing to everyone except a dict lookup. Shared with `hitl` so that the two modes cannot
    disagree about what counts as naming a policy.
    """
    wanted = what.strip().lower().removesuffix(".dw")
    return next((v for k, v in stated.items()
                 if k.lower().removesuffix(".dw") == wanted), None)


def sweep(target: Path, intents: dict[str, str], *, out: Path | None = None,
          build_graph=None, report=None, **kw) -> list[Run]:
    """One pipeline per stated intent. Returns a Run each.

    TWO SHAPES, because policies come both ways:

      a DIRECTORY   one policy per file, each with its own requirement. Enumerated from the
                    directory rather than from the intents file, so a policy with no stated
                    requirement is REPORTED as unstated rather than skipped quietly -- a sweep
                    that silently covers four of six files is a green that means nothing.

      a FILE        one policy set, several requirements against it. This is how a policy is
                    actually deployed, and it is the only shape in which a `forbid`-only rule
                    can be checked at all: alone, under default-deny, it grants nothing, so any
                    claim that something is ALLOWED fails whatever the rule says.
    """
    runs: list[Run] = []
    base = out or (target if target.is_dir() else target.parent) / "anchor"

    # REPORTED AS EACH ONE LANDS, not collected and printed at the end. A sweep is minutes per
    # policy; printing the table afterwards means the whole run shows nothing at all until it is
    # over, and "is it stuck or working?" is exactly the question a long run should answer.
    def done(label: str, run: Run) -> Run:
        runs.append(run)
        if report is not None:
            report(label, run)
        return run

    if target.is_dir():
        for policy in sorted(target.glob("*.dw")):
            if (intent := intents.get(policy.name)):
                if report is not None:
                    report(policy.name, None)
                done(policy.name,
                     _one(policy, intent, base / policy.stem, "Intent", build_graph, kw))
        return runs

    for label, intent in intents.items():
        if report is not None:
            report(label, None)
        done(label, _one(target, intent, base / label, module_name_for(label), build_graph, kw))
    return runs


def screen_inputs(policy: Path, *, intents: Path | None, event_schema: Path | None,
                  intent: str | None, allow: bool) -> tuple[int | None, dict]:
    """Scan everything a model is about to be shown, BEFORE it is shown any of it.

    Returns an exit code to stop with, or None and the `Run` fields that put the scan on the
    record. Shared by `auto` and `hitl` so the two cannot disagree about what gets through.

    What is scanned is what the run will read: the policy (or every input in a directory), the
    intents.md a single policy falls back to, a named --intents file, the event schema, and the
    --intent text itself -- a requirement typed on the command line reaches the drafter exactly as
    a file would, so it is screened exactly as one. See src/checker/scan.py for what is looked for.
    """
    from checker import scan as screen                              # noqa: PLC0415

    root = policy if policy.is_dir() else policy.parent
    paths = [policy, None if policy.is_dir() else root / "intents.md", intents, event_schema]
    report = screen.scan([p for p in paths if p is not None], {"--intent": intent or ""},
                         relative_to=root)
    code = screen.gate(report, allow=allow, who="the model")
    if code is not None:
        return code, {}
    return None, ({"input_scan": report.summary(), "input_scan_overridden": bool(report.high)}
                  if report.high or report.medium else {})


def _one(policy: Path, intent: str, out: Path, module: str, build_graph, kw) -> Run:
    run = Run(policy=policy, intent=intent, out=out, module_name=module, **kw)
    graph = (build_graph or build)(run)
    result = graph(f"State and check the intention for {policy.name}.")
    append_usage(run, result)
    return run


def outcome(run: Run) -> str:
    """One line on what happened, in the order a reader cares about."""
    if run.unreachable:
        return "MODEL UNREACHABLE"
    if run.crashed:
        return "ANCHOR FAILED"
    if run.rejected_at == "confirm":
        # NOT "rejected at confirm". Every other gate refusing a draft is Anchor turning something
        # away; this one is the person saying the claim is not what they meant, which is the mode
        # working rather than the draft failing.
        return "the person said this is not what they meant"
    if run.rejected_at:
        return f"no property (rejected at {run.rejected_at})"
    if run.prop.get("_failed"):
        return "no verdict"
    return "property BROKEN" if not run.prop.get("held") else "property holds"


def sweep_report(target: Path, intents: dict[str, str], runs: list[Run]) -> str:
    root = target if target.is_dir() else target.parent
    unstated = (sorted(p.name for p in target.glob("*.dw") if p.name not in intents)
                if target.is_dir() else [])
    what = "policy/policies" if target.is_dir() else f"requirement(s) against `{target.name}`"
    lines = [f"# {root.name}: {len(runs)} {what}", "",
             "| | outcome | rounds | tokens | findings |", "|---|---|---:|---:|---|"]
    for r, label in zip(runs, intents if not target.is_dir() else [r.policy.name for r in runs]):
        tokens = sum(c.total for c in r.calls)
        # Relative when it can be, absolute when it cannot: `--out` may point anywhere, and
        # `relative_to` RAISES rather than falling back, which would lose the whole summary over a
        # cosmetic path.
        where = "—"
        if r.findings:
            try:
                where = f"`{r.findings.relative_to(root)}`"
            except ValueError:
                where = f"`{r.findings}`"
        lines.append(f"| `{label}` | {outcome(r)} | {r.round} | {tokens:,} | {where} |")

    lines += ["", f"**{sum(sum(c.total for c in r.calls) for r in runs):,} tokens** over "
              f"{sum(len(r.calls) for r in runs)} model calls."]
    if unstated:
        # Named rather than omitted: the set that was checked is only meaningful beside the set
        # that was not.
        lines += ["", "**Not swept**, because `intents.md` states no requirement for them:", ""]
        lines += [f"- `{n}`" for n in unstated]
    lines += ["", "*Every property above was drafted by a model and gated by Anchor. Findings "
              "against an agent-authored property are weaker evidence than findings against one a "
              "person wrote.*", ""]
    return "\n".join(lines)


def absolute(args, *names: str) -> None:
    """Resolve the named path arguments in place. Call it before anything reads them.

    NOT COSMETIC, and the bug it fixes is invisible where most people will look for it.
    `invoke.checker` runs the checker with `cwd=REPO` -- deliberately, so it always sees the Anchor
    tree the same way whoever called it. But argparse resolved a relative path against the CALLER's
    directory, and the two are only the same place when the command was typed inside a checkout.

    In the container they are /app and /work, so `anchor auto examples/aws1` swept six policies and
    rejected all six at `describe` with "no such policy file" -- 0 tokens, six reports, and nothing
    in any of them pointing at a working directory. Resolving here makes the paths mean the same
    thing to every process that is handed one.
    """
    for name in names:
        if (value := getattr(args, name, None)) is not None:
            setattr(args, name, value.resolve())


def main() -> int:
    # ANCHOR_VERB is set by the launcher, so usage names `anchor auto` rather than a file the
    # person never invoked. Unset when the script is run directly, and argparse then does what
    # it always did.
    p = argparse.ArgumentParser(prog=os.environ.get("ANCHOR_VERB") or None,
                                description=__doc__.splitlines()[0])
    p.add_argument("policy", type=Path, help="a .dw policy, or a DIRECTORY to sweep")
    p.add_argument("--intent", default=None,
                   help="the requirement to state formally. Prose the POLICY did not write")
    p.add_argument("--intents", type=Path, default=None,
                   help="for a directory: a markdown file of `## <policy>.dw` headings and the "
                        "requirement under each. Defaults to <directory>/intents.md")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--event-schema", type=Path, default=None)
    p.add_argument("--mutants", type=int, default=8)
    p.add_argument("--max-fields", type=int, default=None,
                   help="raise the checker's bound on how many input/output fields a policy may "
                        "read. Applies to the PROPERTY runs only -- the derived questions range "
                        "over the product of every field domain and do not finish above the "
                        "default, so they are left to refuse instead")
    p.add_argument("--name", default="Intent", help="the property module's name")
    # THE MODEL MATTERS MORE THAN ANY GATE HERE. Drafting a TLA+ property module is the hardest
    # thing this pipeline asks of a model, and the default is a small fast one -- every gate below
    # exists because a weak draft is the norm, not because the gates are the interesting part.
    p.add_argument("--config", type=Path, default=None, metavar="APPSETTINGS.JSON",
                   help="the settings file holding the model configuration and API key. Defaults "
                        "to appsettings.json beside src/agent/ or at the repo root; in a container "
                        "this is how a mounted one is named")
    p.add_argument("--provider", default="auto", help="auto, bedrock or gemini")
    p.add_argument("--llm", default=None,
                   help="the LLM's model id. Defaults to the provider's own default (gemini-2.5-flash for "
                        "Gemini), which is a small model for a hard task")
    p.add_argument("--rounds", type=int, default=3,
                   help="drafting attempts. A round costs one model call plus ~1s of SANY; "
                        "running out still reports (default: 3)")
    p.add_argument("--turns", type=int, default=None,
                   help="cap on agent loop iterations PER CALL -- one model call plus the tools "
                        "it asked for. Not cumulative: --rounds R with --turns T allows R*T")
    p.add_argument("--total-tokens", type=int, default=None,
                   help="cap on input+output tokens per call")
    p.add_argument("--output-tokens", type=int, default=None,
                   help="cap on generated tokens per call. Soft: one oversized response can "
                        "overshoot, since caps are checked at turn boundaries")
    p.add_argument("--max-node-executions", type=int, default=None,
                   help="backstop on total node executions. Hitting it STOPS THE RUN WITH NO "
                        "REPORT, so it is set above what the graph can use; lower it only to "
                        "observe that behaviour")
    p.add_argument("--node-timeout", type=float, default=None,
                   help="per-node seconds. A node that times out fails, and a failed node "
                        "fail-fasts the whole run -- so this too can end a run with no report. "
                        "`score` runs TLC per mutant and is the one that would hit it")
    p.add_argument("--verbose", action="store_true",
                   help="leave third-party logging alone; see the note below")
    p.add_argument("--allow-flagged-input", action="store_true",
                   help="show the model inputs the scan flagged as high severity anyway. For a "
                        "finding you have READ and judged benign -- a comment that discusses "
                        "prompt injection, say. findings.md records that it was used")
    args = p.parse_args()

    # Before anything is read from them, and before the sweep globs children off `policy`.
    absolute(args, "policy", "intents", "out", "event_schema")

    # BEFORE ANY MODEL IS SHOWN ANYTHING. The policy is often under analysis precisely because it
    # is not trusted, and everything past this point hands its text to a model.
    blocked, scanned = screen_inputs(args.policy, intents=args.intents,
                                     event_schema=args.event_schema, intent=args.intent,
                                     allow=args.allow_flagged_input)
    if blocked is not None:
        return blocked

    # BEFORE anything builds a model, and before the graph is built at all: every read of this
    # file happens inside policy_agent, lazily, so setting it here reaches all of them.
    if args.config is not None:
        policy_agent.use_appsettings(args.config)

    if not args.verbose:
        # google-genai warns, once per process, that strands calls generate_content_stream
        # directly rather than through AsyncChat. It is advice to the SDK that wraps it, not to
        # anything a reader of this output can act on, and it lands in the middle of a report.
        #
        # Quieted HERE and not at import: this is the command line's choice about its own
        # stdout, and a library that imports `pipeline` keeps whatever logging it configured.
        import logging                                                 # noqa: PLC0415
        logging.getLogger("google_genai.models").setLevel(logging.ERROR)

    shared = dict(event_schema=args.event_schema, module_name=args.name, mutants=args.mutants,
                  rounds=args.rounds, max_fields=args.max_fields,
                  limits={k: v for k, v in (("turns", args.turns),
                                            ("total_tokens", args.total_tokens),
                                            ("output_tokens", args.output_tokens)) if v},
                  **scanned)

    if args.policy.is_dir() or args.intents:
        intents_file = args.intents or args.policy / "intents.md"
        if not intents_file.exists():
            print(f"no intents file at {intents_file}. A sweep needs a requirement per policy, "
                  f"stated somewhere the policies did not write it.", file=sys.stderr)
            return 2
        intents = read_intents(intents_file)
        root = args.policy if args.policy.is_dir() else args.policy.parent
        out = args.out or root / "anchor"

        # `module_name` is chosen per intent inside the sweep -- one module per requirement, named
        # from its heading -- so the single-policy default must not be passed alongside it.
        per_run = {k: v for k, v in shared.items() if k != "module_name"}

        print(f"sweeping {len(intents)} intent(s) against {args.policy} (this makes live model "
              f"calls)\n", file=sys.stderr)
        def progress(label: str, run: Run | None) -> None:
            if run is None:
                print(f"  {label:<32} ...", end="\r", file=sys.stderr, flush=True)
                return
            spent = sum(c.total for c in run.calls)
            print(f"  {label:<32} {outcome(run):<34} {spent:>7,} tokens, {run.round} round(s)",
                  file=sys.stderr, flush=True)

        runs = sweep(args.policy, intents, out=out, report=progress,
                     build_graph=lambda r: build(r, provider=args.provider, model=args.llm),
                     **per_run)

        out.mkdir(parents=True, exist_ok=True)
        summary = out / "summary.md"
        summary.write_text(sweep_report(args.policy, intents, runs), encoding="utf-8")
        print(f"\n{sum(sum(c.total for c in r.calls) for r in runs):,} tokens over "
              f"{sum(len(r.calls) for r in runs)} model calls", file=sys.stderr)
        print(summary)
        return 1 if any(r.crashed or r.rejected_at for r in runs) else 0

    # NO --intent, so look where `hitl` looks: a heading naming this policy in the intents.md
    # beside it. `--intents` is NOT the spelling for this -- with a single policy that flag means
    # "run EVERY heading in the named file against this one policy", which is a different and
    # deliberate mode, so the useful default had to be what OMITTING it does.
    beside = args.policy.parent / "intents.md"
    if not args.intent and beside.is_file():
        if (stated := intent_for(read_intents(beside), args.policy.name)):
            print(f"{beside.name} states: {stated}", file=sys.stderr)
            args.intent = stated

    if not args.intent:
        # Two situations, two different fixes: a file that says nothing about this policy, or
        # no file at all. "Add a heading to that file" when there is no file is the kind of
        # advice that costs somebody a minute of looking for it.
        where, how = ((f"and no heading for {args.policy.name} in {beside}",
                       f"add a `## {args.policy.name}` heading to that file")
                      if beside.is_file() else
                      (f"and there is no {beside}",
                       f"create it with a `## {args.policy.name}` heading"))
        print(f"no requirement for this policy: --intent was not given, {where}.\n"
              f"Pass --intent \"...\", or {how}.", file=sys.stderr)
        return 2

    run = Run(policy=args.policy, intent=args.intent,
              out=args.out or args.policy.parent / "anchor", **shared)

    graph = build(run, provider=args.provider, model=args.llm,
                  max_node_executions=args.max_node_executions, node_timeout=args.node_timeout)
    result = graph(f"State and check the intention for {args.policy.name}.")

    append_usage(run, result)

    ran = [n.node_id for n in result.execution_order]
    print(f"\nran {len(ran)}/{result.total_nodes}: {', '.join(ran)}", file=sys.stderr)
    print(f"{sum(c.total for c in run.calls):,} tokens over {len(run.calls)} model call(s); "
          f"{(getattr(result, 'execution_time', 0) or 0) / 1000:.1f}s total", file=sys.stderr)
    for c in run.capped:
        print(f"CAP: {c}", file=sys.stderr)
    if run.findings:
        print(run.findings)
    # A rejected draft is a complete run with nothing verified, and that is not a success.
    return 1 if run.rejected_at else 0


if __name__ == "__main__":
    sys.exit(main())
