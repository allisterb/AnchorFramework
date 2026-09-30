"""`src/agent/pipeline.py` end to end, and the claim that makes it worth having.

Nine scenarios, and the first is the one the whole graph exercise was for:

  1. THE SHAPE THAT RUNS IS THE SHAPE THAT WAS CHECKED. `to_tla` over the graph `pipeline.build`
     actually returns must carry all four gate decisions as exclusive pairs, and must satisfy
     `AlwaysReports` -- the same claim, over the same module, that tests/strands/anchor_workflow.py
     proves about the `gated` variant. Without this the design work checked a drawing.
  2. A DRAFT THAT WILL NOT COMPILE is retried, having been told the line and the token. This is
     the failure a live run hit, over one stray `*`. The retry lives inside the `draft` node, so
     the graph stays acyclic -- asserted, because a cycle would put it outside what either model
     can express.
  3. NOTHING ABORTS THE RUN. A node that RAISES ends the run with no findings.md at all, which
     is the hole `AlwaysReports` cannot cover -- it is stated over `phase = "DONE"`, and the
     property cannot be strengthened because the model lets any node fail. So the obligation is
     discharged in code: every stage catches, and an unreadable policy is a gate rejection.
  4. RUNNING OUT OF ROUNDS is not a crash and not a silence: the last attempt is judged by the
     same gates, and findings.md says the allowance ran out.
  5. A BUDGET CAP is neither a bad draft nor a finished report. A cut-off draft is a failed
     round; a cut-off report says so of itself, because a truncated report that does not reads
     as a complete one.
  6. A REJECTED DRAFT still reports, without a TLC run or a second model call.
  7. AN ACCEPTED DRAFT goes the whole way, and the answerer sees the verdicts and their BOUND
     rather than the drafter's module.
  8. THE ROUND TRIP. A third agent, shown only the BRIEF and the plain-English reading of the
     claim -- never the formal claim, never the policy -- says whether they match. It is the one
     gate that compares the property against the requirement rather than against the policy, and
     the only one with no oracle behind it: it may REJECT, and its agreement is reported as an
     agreement between two models rather than as a verification.
  9. A SWEEP over a directory runs one pipeline per STATED intent, names the policies that have
     none, and discriminates: the same drafted property holds on the sound policy and breaks on
     the unsound one.

No provider and no credentials: every agent is scripted, so the only cost is the TLC runs behind
the `score` gate.

    python tests/strands/pipeline_run.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from anchor_workflow import check_intent                               # noqa: E402
from translator.strands_graph_to_tla import to_tla                     # noqa: E402

from strands import Agent                                              # noqa: E402
from strands.models import Model                                       # noqa: E402
from strands.types.content import Messages                             # noqa: E402
from strands.types.event_loop import Usage                             # noqa: E402
from strands.types.tools import ToolSpec                               # noqa: E402

from agent import pipeline                                             # noqa: E402
# Where the engine is, honouring ANCHOR_DOGWOOD; without it a broken property says why it was
# not confirmed rather than failing.
from checker.engine import DOGWOOD                                     # noqa: E402

POLICIES = REPO / "tests" / "policies"


class Fixed(Model):
    """A model that says one thing. Stands in for the drafter and the answerer."""

    def __init__(self, text: str) -> None:
        self.text, self.calls = text, 0

    def get_config(self) -> Any:
        return {}

    def update_config(self, **model_config: Any) -> None:
        pass

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError

    async def stream(self, messages: Messages, tool_specs: list[ToolSpec] | None = None,
                     system_prompt: str | None = None, tool_choice: Any | None = None, *,
                     system_prompt_content=None, **kwargs: Any) -> AsyncGenerator[Any, None]:
        self.calls += 1
        self.seen = pipeline.incoming(messages)
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": self.text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        # A FIXED, NON-ZERO COST PER CALL. Zero would make the accounting untestable: the whole
        # question is whether a second call to the SAME agent reports its own usage or the running
        # total, and 0 + 0 looks the same either way.
        yield {"metadata": {"usage": Usage(inputTokens=10, outputTokens=5, totalTokens=15),
                            "metrics": {"latencyMs": 0}}}


class Scripted(Fixed):
    """A different reply per call, so a retry can be told apart from a repeat."""

    def __init__(self, *texts: str) -> None:
        super().__init__(texts[0])
        self.texts, self.prompts = texts, []

    async def stream(self, messages, *a, **kw):                # type: ignore[override]
        self.prompts.append(pipeline.incoming(messages))
        self.text = self.texts[min(self.calls, len(self.texts) - 1)]
        async for event in super().stream(messages, *a, **kw):
            yield event


class Capped(Fixed):
    """Stops the way a tripped budget cap stops: a stop_reason, and a truncated reply.

    Simulated rather than provoked, because a `turns` cap cannot fire on an agent with no tools --
    one turn always completes. The shape is what matters and it is the SDK's own: stop_reason
    `limit_turns` / `limit_total_tokens` / `limit_output_tokens`, returned normally.
    """

    def __init__(self, text: str, reason: str = "limit_output_tokens") -> None:
        super().__init__(text)
        self.reason = reason

    async def stream(self, messages, *a, **kw):                # type: ignore[override]
        self.calls += 1
        self.seen = pipeline.incoming(messages)
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": self.text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": self.reason}}


class Unreachable(Fixed):
    """Refuses the way Gemini refuses a model id it does not have, through an Agent Platform key."""

    def __init__(self) -> None:
        super().__init__("")

    async def stream(self, messages, *a, **kw):                # type: ignore[override]
        self.calls += 1
        raise RuntimeError(
            "404 NOT_FOUND. {'error': {'code': 404, 'message': 'Publisher model `projects/p/"
            "locations/global/publishers/google/models/gemini-2.7.-flash` was not found or your "
            "project does not have access to it.', 'status': 'NOT_FOUND'}}")
        yield                                                  # an async generator all the same


def agent(text: str, name: str) -> Agent:
    return Agent(model=Fixed(text), callback_handler=None, name=name)


def scripted(name: str, *texts: str) -> Agent:
    return Agent(model=Scripted(*texts), callback_handler=None, name=name)


# The draft a live run actually produced: right in every respect but one stray `*` after a comment
# terminator, which SANY rejects and no amount of re-reading catches.
WONT_COMPILE = "===MODULE===\n" + (POLICIES / "firewall_unparseable.tla").read_text(
    encoding="utf-8").replace("MODULE firewall_unparseable", "MODULE Intent", 1) + (
    "\n===CONFIG===\n" + (POLICIES / "firewall.cfg").read_text(encoding="utf-8"))


# A draft that holds and discriminates: tests/policies/firewall.tla, renamed to the module name the
# loop chose. Real, and checked in -- inventing one here would be checking the harness.
GOOD = "===MODULE===\n" + (POLICIES / "firewall.tla").read_text(encoding="utf-8").replace(
    "MODULE firewall", "MODULE Intent", 1) + "\n===CONFIG===\n" + (
    POLICIES / "firewall.cfg").read_text(encoding="utf-8")

# A draft whose .cfg names an invariant the module never defines. TLC would stop with an error
# rather than check anything, which is why this is a hard rejection and not a warning.
BAD = """===MODULE===
---------------------------- MODULE Intent ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest
VARIABLE req
Init == req = 1
Next == UNCHANGED req
Spec == Init /\\ [][Next]_req
=============================================================================
===CONFIG===
SPECIFICATION Spec
INVARIANT OutsideIsRefused
"""

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)
        if detail:
            print(f"          {detail[:400]}")


def run_pipeline(draft, out: Path, mutants: int = 2, rounds: int = 3, reviewer=None):
    run = pipeline.Run(policy=POLICIES / "firewall.dw",
                       intent="SSH from the local range is permitted, and every external source "
                              "is denied.",
                       out=out, mutants=mutants, rounds=rounds)
    drafter = draft if isinstance(draft, Agent) else agent(draft, "draft")
    answerer = agent("The property held.", "answer")
    graph = pipeline.build(run, drafter=drafter, answerer=answerer,
                           reviewer=reviewer or agent("VERDICT: MATCH -- it says the same.",
                                                      "review"))
    result = graph("State and check the intention for firewall.dw.")
    pipeline.append_usage(run, result)
    return run, result, [n.node_id for n in result.execution_order], answerer


def retries() -> None:
    """The failure a live run hit: a module that will not compile, fixed by being told where."""
    print("\nA draft that does not compile, and the round that fixes it")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        drafter = scripted("draft", WONT_COMPILE, GOOD)
        run, result, ran, _ = run_pipeline(drafter, Path(tmp))

        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}  "
              f"({run.round} drafting round(s))")
        check("it took a second round", run.round == 2, str(run.round))
        check("and the run then completed", set(ran) == set(pipeline.STAGES), str(sorted(set(ran))))
        check("not rejected", run.rejected_at == "", run.rejected_at)

        # A complaint without a LOCATION is one no round can act on. SANY has it; nothing else in
        # the pipeline does.
        second = drafter.model.prompts[1]                      # type: ignore[attr-defined]
        check("round 2 was told the module did not compile",
              "did not compile" in second, second[:200])
        check("...and where SANY choked",
              "Parse Error" in second and re.search(r"at line \d+, column \d+", second) is not None,
              second[-400:])

        # AND IT DID NOT PAY FOR THE MANUAL TWICE. One Agent runs every round, so its conversation
        # already holds round 1 — prompt, manual, vocabulary and all. Building round 2 from
        # `draft_prompt` sent a second copy of 15 KB of manual plus 8 KB of vocabulary on top of
        # that history: measured on a live run, round 2's input was 19,501 tokens of which 6,522
        # was exactly this. `prompts[1]` is the whole conversation as the model saw it, so the
        # count is over both rounds together.
        check("...and the manual was not sent a second time",
              second.count("title: Writing a property module") == 1,
              f"the manual appears {second.count('title: Writing a property module')} time(s)")
        check("...nor the vocabulary", second.count('"requiredModuleName"') == 1,
              f"the vocabulary appears {second.count('\"requiredModuleName\"')} time(s)")

        # THE RETRY IS INSIDE ONE NODE, which is why the graph is still acyclic and still the
        # shape the models checked. If `draft` ever starts appearing twice, a cycle has been
        # introduced and neither model can express it -- see stage_draft's docstring.
        check("the graph stayed acyclic: draft ran once", ran.count("draft") == 1, str(ran))

        # THE ACCOUNTING TRAP, and this is the only scenario that can catch it: the drafter is
        # called TWICE on the same Agent object. `metrics.accumulated_usage` is cumulative across
        # invocations, so reading it per call would bill round 1 again on round 2 -- 15 then 30,
        # totalling 45 for two calls that each cost 15. Silent, and it grows with the round count.
        drafts = [c for c in run.calls if c.who.startswith("draft")]
        check("two drafting rounds were billed", len(drafts) == 2, str([c.who for c in run.calls]))
        check("...each at ITS OWN cost, not the agent's running total",
              [c.total for c in drafts] == [15, 15], str([c.total for c in drafts]))


def never_aborts() -> None:
    """No stage may raise, because a raised stage means no findings.md at all.

    This is the hole `AlwaysReports` cannot cover: it is stated over `phase = "DONE"`, and a node
    that raises ends the run ABORTED. The property cannot be strengthened -- the model lets any
    node fail, so no shape would satisfy it -- so the obligation is discharged in the code, and
    this is where that is checked.
    """
    print("\nNothing aborts the run")
    print("-" * 78)

    # --- a policy that cannot be read ----------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run = pipeline.Run(policy=POLICIES / "does_not_exist.dw", intent="x", out=Path(tmp))
        graph = pipeline.build(run, drafter=agent(GOOD, "draft"), answerer=agent("ok", "answer"),
                               reviewer=agent("VERDICT: MATCH", "review"))
        result = graph("go")
        ran = [n.node_id for n in result.execution_order]

        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}")
        check("an unreadable policy is a rejection, not an abort",
              str(result.status) != "Status.FAILED" and run.rejected_at == "describe",
              f"{result.status} / {run.rejected_at}")
        check("nothing after describe ran", ran == ["describe", "report"], str(ran))
        check("and it still reported",
              run.findings is not None and run.findings.exists())

    # --- a stage that throws outright ----------------------------------------------------------
    # The generic case, and the one that guards against a stage nobody anticipated failing.
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent="x", out=Path(tmp), mutants=2)
        boom = pipeline.stage_check
        try:
            pipeline.stage_check = lambda r, t: 1 / 0          # type: ignore[assignment]
            graph = pipeline.build(run, drafter=agent(GOOD, "draft"),
                                   answerer=agent("ok", "answer"),
                                   reviewer=agent("VERDICT: MATCH", "review"))
            result = graph("go")
        finally:
            pipeline.stage_check = boom                        # type: ignore[assignment]

        ran = [n.node_id for n in result.execution_order]
        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}")
        check("a stage that throws does not abort the run",
              str(result.status) != "Status.FAILED", str(result.status))
        check("report still ran", "report" in ran, str(ran))
        check("the crash is recorded", any("check" in c for c in run.crashed), str(run.crashed))

        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("findings.md says it was ANCHOR that failed, not the policy",
              "a bug in Anchor" in text and "not a finding about your policy" in text, text[:400])


def capped() -> None:
    """A budget cap must not read as a bad draft, or as a finished report."""
    print("\nA budget cap fires")
    print("-" * 78)

    # --- the DRAFTER is cut off -------------------------------------------------------------
    # Left alone this reaches the gates as a half-written module, is rejected for not compiling,
    # and the report blames the model for a syntax error that was really a budget running out.
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        cut = Agent(model=Capped("===MODULE===\n---- MODULE Int"), callback_handler=None,
                    name="draft")
        run, result, ran, _ = run_pipeline(cut, Path(tmp), rounds=2)

        check("a cut-off draft is a failed round, not a draft",
              run.round == 2 and run.exhausted, f"round={run.round} exhausted={run.exhausted}")
        check("and the cap is recorded against the round that hit it",
              len(run.capped) == 2 and "draft round 1" in run.capped[0], str(run.capped))
        check("the run still reported", "report" in ran, str(ran))

        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("findings.md leads with the cap", "A budget cap fired" in text, text[:300])
        check("...and names which cap", "limit_output_tokens" in text, text[:400])

    # --- the REPORTER is cut off -------------------------------------------------------------
    # The dangerous one: a truncated report that does not say so reads as a complete one, and
    # nothing in the verdicts would tell the reader otherwise.
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent="x", out=Path(tmp), mutants=2)
        graph = pipeline.build(run, drafter=agent(GOOD, "draft"),
                               answerer=Agent(model=Capped("The property h"),
                                              callback_handler=None, name="answer"),
                               reviewer=agent("VERDICT: MATCH", "review"))
        result = graph("go")
        ran = [n.node_id for n in result.execution_order]

        check("the run completed", set(ran) == set(pipeline.STAGES), str(sorted(set(ran))))
        check("the cap on the reporter was caught",
              any("the report" in c for c in run.capped), str(run.capped))
        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("the report says of ITSELF that it is incomplete",
              "cut off by a budget cap and is incomplete" in text, text[-400:])


def exhausted() -> None:
    """Running out of rounds is not a crash, and must not be a silent one either."""
    print("\nRounds exhausted")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        drafter = scripted("draft", WONT_COMPILE)              # never improves
        run, result, ran, answerer = run_pipeline(drafter, Path(tmp), rounds=2)

        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}  "
              f"({run.round} round(s), exhausted={run.exhausted})")
        check("every round was used", run.round == 2, str(run.round))
        check("and the allowance is recorded as spent", run.exhausted is True)
        check("the run was NOT aborted", result.status.value != "failed", str(result.status))
        check("report still ran", "report" in ran, str(ran))
        check("the answerer was not invoked", answerer.model.calls == 0)

        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("findings.md says the allowance ran out", "allowance ran out" in text, text[:400])
        check("...and that nothing was verified", "nothing here was verified" in text)


def rejected_path() -> None:
    print("\nA draft the static gate turns away")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run, result, ran, answerer = run_pipeline(BAD, Path(tmp))

        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}")
        check("rejected at preflight", run.rejected_at == "preflight", str(run.complaints))
        check("the complaint names the undefined invariant",
              any("OutsideIsRefused" in c for c in run.complaints), str(run.complaints))

        # THE POINT OF GATING BEFORE THE EXPENSIVE STEP. Nothing downstream ran: no TLC, and the
        # second model was never called.
        check("score, check and answer never ran",
              not ({"score", "check", "answer"} & set(ran)), str(ran))
        check("the answerer was not invoked", answerer.model.calls == 0)

        # ...and it still reported, which is the property `AlwaysReports` states.
        check("report ran anyway", "report" in ran, str(ran))
        check("findings.md exists", run.findings is not None and run.findings.exists())
        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("findings.md says nothing was verified", "nothing here was verified" in text)
        check("...and names the gate", "`preflight`" in text, text[:200])


def accepted_path() -> None:
    print("\nA draft that holds and discriminates")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run, result, ran, answerer = run_pipeline(GOOD, Path(tmp))

        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}")
        check("not rejected", run.rejected_at == "", run.rejected_at or "")
        check("every stage ran", set(ran) == set(pipeline.STAGES), str(sorted(set(ran))))
        check("the property was scored against mutants", run.score.get("caught") is not None,
              str(run.score.get("exitCode")))
        check("the checks ran", bool(run.checked), run.checked[:200])

        # THE SEPARATION, as it actually lands: the answerer's input contains the verdicts and not
        # the drafter's module text. Nothing enforces this but the wiring, so it is checked.
        seen = getattr(answerer.model, "seen", "")
        check("the answerer saw the verdicts", "The stated property" in seen, seen[:200])
        check("the answerer did NOT see the draft", "===MODULE===" not in seen, seen[:200])

        # THE BOUND REACHES THE REPORTER. "Holds" on its own is the most overclaimable sentence
        # this pipeline emits, and a live run produced exactly the overclaim -- "for all possible
        # requests and scenarios", "guaranteed" -- because nothing it was given said otherwise.
        check("the answerer was told what the property RANGES OVER",
              "WHAT WAS ACTUALLY CHECKED" in seen and "claim" in seen, seen[-300:])
        check("...including the states each claim applies to",
              "applies" in seen, seen[-300:])

        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("findings.md carries the verdicts", "## Verdicts" in text)
        check("...and says the property was agent-authored", "weaker evidence" in text)

        # Strands frames a node's input; that framing was landing in findings.md under a heading
        # promising the reporter's own words.
        check("the report does not carry Strands' input scaffolding",
              "Inputs from previous nodes" not in text and "Original Task:" not in text,
              text[-400:])

        # --- WHAT IT COST ---------------------------------------------------------------------
        check("findings.md reports the cost", "## What this run cost" in text, text[-600:])
        check("one row per model call", len(run.calls) == 3,
              str([c.who for c in run.calls]))
        check("and a per-stage time for every stage that ran",
              all(f"  {s:<12}" in text for s in pipeline.STAGES), text[-800:])

        check("with the tokens each one cost", all(c.total == 15 for c in run.calls),
              str([(c.who, c.total) for c in run.calls]))


def same_object() -> None:
    """The claim the graph work exists to support."""
    print("\nThe shape that runs is the shape that was checked")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent="x", out=Path(tmp))
        graph = pipeline.build(run, drafter=agent(GOOD, "draft"), answerer=agent("ok", "answer"),
                               reviewer=agent("VERDICT: MATCH", "review"))

        t = to_tla(graph)
        check("all four gates declared as exclusive decisions", len(t.exclusive) == 4,
              str(t.exclusive))
        check("no half-decisions", t.unpaired == [], str(t.unpaired))
        check("no undeclared assumptions", t.assumptions == [], str(t.assumptions))

        for name, a, b in t.exclusive:
            print(f"    {name:<10} accept {a}   reject {b}")

        holds, output = check_intent(t.tla)
        check("AlwaysReports HOLDS on the graph that actually runs", holds,
              "\n".join(output.splitlines()[-8:]))

        # The separation, enforced by the SDK rather than by this file.
        check("the drafter and the answerer are different objects",
              graph.nodes["draft"].executor is not graph.nodes["answer"].executor)


def round_trip() -> None:
    """The one gate that compares the property against the BRIEF rather than against the policy."""
    print("\nThe round trip: does it say what was asked for?")
    print("-" * 78)

    # --- a reviewer that disagrees stops the run ------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        no = agent("VERDICT: MISMATCH\nThe requirement is about refunds; this is about SSH.",
                   "review")
        run, result, ran, answerer = run_pipeline(GOOD, Path(tmp), reviewer=no)

        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}")
        check("a mismatch stops the run at review", run.rejected_at == "review", run.rejected_at)
        check("check and answer never ran", not ({"check", "answer"} & set(ran)), str(ran))
        check("the answerer was not invoked", answerer.model.calls == 0)
        check("report ran anyway", "report" in ran, str(ran))

        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("findings.md carries the reviewer's reasoning",
              "about SSH" in text and "do not match" in text, text[:400])

    # --- and what an AGREEMENT is allowed to claim ----------------------------------------------
    # This gate has no oracle: every other one is a criterion in code, this is a model judging a
    # model. So agreement must be reported as agreement. If this assertion ever has to change
    # because the wording got stronger, that is the bug it exists to catch.
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        run, result, ran, _ = run_pipeline(GOOD, Path(tmp))
        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("an agreement is reported as an agreement, not a proof",
              "not a proof that the claim captures the requirement" in text, text[:500])
        check("...and says the reviewer never saw the formal claim",
              "never the formal claim itself" in text, text[:500])

    # --- a reviewer that answers in no recognisable form must NOT block --------------------------
    # Fail-open is right HERE and only here: acceptance proves nothing anyway, so blocking on a
    # non-answer would give this gate an authority the other gates have and it does not.
    with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
        vague = agent("I think it's probably fine, hard to say really.", "review")
        run, result, ran, _ = run_pipeline(GOOD, Path(tmp), reviewer=vague)
        check("an unparseable review does not stop the run", run.rejected_at == "", run.rejected_at)
        check("...and the report says the round trip was NOT established",
              "not established" in (run.findings.read_text(encoding="utf-8") if run.findings
                                    else ""), run.review)


def sweeping() -> None:
    """A directory of policies, and the set that was NOT swept named beside it."""
    print("\nSweeping a directory")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-sweep-") as tmp:
        work = Path(tmp)
        for name in ("firewall.dw", "firewall_open.dw", "dead_forbid.dw"):
            (work / name).write_text((POLICIES / name).read_text(encoding="utf-8"),
                                     encoding="utf-8")
        # Two of the three get an intent. The third must be REPORTED as unstated, not skipped:
        # a sweep that quietly covers two thirds of a directory is a green that means nothing.
        (work / "intents.md").write_text(
            "# Intents\n\n## firewall.dw\n\n> Local SSH is permitted and every external source is "
            "denied.\n\n## firewall_open.dw\n\n> Local SSH is permitted and every external source "
            "is denied.\n", encoding="utf-8")

        intents = pipeline.read_intents(work / "intents.md")
        check("both stated intents were read", len(intents) == 2, str(sorted(intents)))

        # PROGRESS AS IT LANDS. A sweep is minutes per policy, and collecting the outcomes to print
        # a table at the end means the whole run shows nothing until it is over -- which is the
        # same defect the report itself exists to avoid, in the terminal instead of the document.
        seen: list[tuple[str, bool]] = []
        runs = pipeline.sweep(work, intents, out=work / "anchor", mutants=2,
                              report=lambda label, run: seen.append((label, run is None)),
                              build_graph=lambda r: pipeline.build(
                                  r, drafter=agent(GOOD, "draft"), answerer=agent("ok", "answer"),
                                  reviewer=agent("VERDICT: MATCH", "review")))
        check("one run per stated intent", len(runs) == 2, str([r.policy.name for r in runs]))
        check("each policy is announced BEFORE it runs and reported after",
              seen == [("firewall.dw", True), ("firewall.dw", False),
                       ("firewall_open.dw", True), ("firewall_open.dw", False)], str(seen))

        # The same property against a policy that HOLDS it and one that BREAKS it -- so the sweep
        # is shown to discriminate rather than merely to complete.
        by = {r.policy.name: pipeline.outcome(r) for r in runs}
        print(f"  {by}")
        check("the correct policy passes", by.get("firewall.dw") == "property holds", str(by))
        check("and the broken one is caught",
              by.get("firewall_open.dw") == "property BROKEN", str(by))

        report = pipeline.sweep_report(work, intents, runs)
        check("the summary names the policy with no stated intent",
              "dead_forbid.dw" in report and "Not swept" in report, report[-400:])
        check("...and totals the tokens", "tokens** over" in report, report[-400:])


def says_what_it_is_doing() -> None:
    """10. AN UNATTENDED RUN SAYS WHAT IT IS DOING, as it does it.

    `auto` printed nothing between the command and its closing summary: minutes of drafting and
    TLC looking identical to a hang. This runs its real `main`, with every agent scripted and a
    stand-in that raises if a real model is ever built, and reads what it said on stderr.
    """
    print("\nAn unattended run says what it is doing")
    print("-" * 78)
    from agent import invoke, policy_agent

    def no_model(*_a, **_k):
        raise AssertionError("a real model was built")

    real_build, real_readiness, real_model = pipeline.build, policy_agent.readiness, policy_agent.build_model
    policy_agent.build_model = no_model
    pipeline.build = lambda run, **kw: real_build(
        run, drafter=agent(GOOD, "draft"), answerer=agent("The property held.", "answer"),
        reviewer=agent("VERDICT: MATCH -- it says the same.", "review"), **kw)
    invoke.clear()                   # a remembered answer relays nothing, and this reads the relay
    try:
        with tempfile.TemporaryDirectory(prefix="anchor-pipe-") as tmp:
            argv = [str(POLICIES / "firewall.dw"), "--intent", "SSH from the local range is "
                    "permitted, and every external source is denied.", "--out", tmp, "--mutants", "2"]

            # Nothing configured: refused before any stage, with the reason.
            policy_agent.readiness = lambda *a, **k: policy_agent.Readiness(
                "gemini", "x", problems=["no Gemini API key: (stand-in)"])
            code, said = run_main(argv)
            check("an LLM that cannot be built stops auto before any stage, exit 3",
                  code == 3 and "no Gemini API key" in said and "[describe]" not in said,
                  f"{code}\n{said[-600:]}")

            policy_agent.readiness = lambda *a, **k: policy_agent.Readiness(
                "gemini", "stand-in", source="none (scripted)", model_source="scripted")
            code, said = run_main(argv)
            check("the run is described before it starts",
                  "Drafting a property module for" in said and "from --intent:" in said
                  and said.index("Drafting a property module") < said.index("[describe]"),
                  said[:800])
            check("every stage says when it starts and when it ends",
                  all(f"[{s}]" in said and f"-> {s} done" in said
                      for s in ("describe", "draft", "preflight", "score", "check", "report")),
                  said[-1500:])
            check("each mutant's TLC run is relayed as it starts",
                  "TLC 1/2  mutant:" in said and "TLC 2/2  mutant:" in said, said[-1500:])
            check("nothing is drawn over in place, so a CI log reads the same", "\r" not in said)
            check("...and the run itself is unchanged", code == 0, f"{code}\n{said[-600:]}")

            # THE VERDICTS AT THE END, so nobody has to open findings.md -- or think a separate
            # `check` is needed -- to learn what the run found; and the way on to a full audit.
            check("the end of the run gives the property's verdict",
                  "the stated property HOLDS (Intent.tla)" in said, said[-900:])
            check("...and the derived findings", "derived findings: 1 (forbid #2 DEAD)" in said,
                  said[-900:])
            check("...and the audit that goes further",
                  "to audit with it: anchor check" in said and "--full --property" in said,
                  said[-900:])
            text = (Path(tmp) / "findings.md").read_text(encoding="utf-8")
            check("findings.md carries the same command",
                  "To audit the policy set with this property" in text and "--full --property" in text,
                  text[-1200:])

            # A BROKEN property: the session that breaks it, replayed in Dogwood as the audit does.
            broken = [str(POLICIES / "firewall_open.dw"), *argv[1:]]
            code, said = run_main(broken)
            text = (Path(tmp) / "findings.md").read_text(encoding="utf-8")
            engine = DOGWOOD.exists()
            check("a BROKEN property is said at the end, as the session that breaks it",
                  "the stated property is BROKEN (Intent.tla):" in said
                  and ("the Dogwood engine" in said if engine else "dogwood binary" in said),
                  said[-1200:])
            check("...replayed in Dogwood in findings.md, with the trace kept beside it",
                  "In Dogwood:" in text and (not engine or (Path(tmp) / "witness").is_dir()),
                  text[-1500:])
            check("...and exits 1: findings, not a failure to run", code == 1, str(code))

            # A draft the reviewer turns away: nothing is checked, and the end of the run must say
            # why rather than only where -- "rejected at review" sent a person to findings.md.
            pipeline.build = lambda run, **kw: real_build(
                run, drafter=agent(GOOD, "draft"), answerer=agent("ok", "answer"),
                reviewer=agent("VERDICT: MISMATCH -- the requirement makes the steps necessary, "
                               "and the claim makes them sufficient.", "review"), **kw)
            code, said = run_main(argv)
            check("a rejected draft says at the end why it was rejected",
                  "outcome: no property (rejected at review)" in said
                  and "makes them sufficient" in said.split("outcome:")[-1], said[-900:])
            check("...that nothing was checked, and what hitl would do instead",
                  "nothing was checked. `anchor hitl`" in said, said[-900:])
            check("...and exits 1", code == 1, str(code))

            # A model id the provider does not have, as google-genai reports it through an Agent
            # Platform key. It must be said where it happened and at the end, never as `done`.
            pipeline.build = lambda run, **kw: real_build(
                run, drafter=Agent(model=Unreachable(), callback_handler=None, name="draft"),
                answerer=agent("ok", "answer"), reviewer=agent("VERDICT: MATCH", "review"), **kw)
            code, said = run_main(argv)
            check("an LLM that cannot be reached fails its stage, not `done`",
                  "-> draft FAILED" in said and "-> draft done" not in said, said[-1200:])
            check("...says why in the provider's own words, explained",
                  "404 NOT_FOUND: Publisher model" in said
                  and "Google has no model by that name" in said, said[-1200:])
            check("...says so again at the end", "outcome: MODEL UNREACHABLE" in said
                  and "error: the LLM could not be reached" in said, said[-800:])
            check("...and exits 3, not the rejected-draft 1", code == 3, str(code))
    finally:
        pipeline.build, policy_agent.readiness, policy_agent.build_model = (
            real_build, real_readiness, real_model)
        invoke.progress = None


def run_main(argv: list[str]) -> tuple[int, str]:
    """`auto`'s main with this argv, and what it said on stderr."""
    import contextlib
    import io

    said = io.StringIO()
    sys.argv = ["pipeline.py", *argv]
    with contextlib.redirect_stderr(said), contextlib.redirect_stdout(io.StringIO()):
        code = pipeline.main()
    return code, said.getvalue()


def main() -> int:
    print("=" * 78)
    print("Anchor's property-authoring pipeline, as the graph that runs it")
    print("=" * 78)

    same_object()
    retries()
    never_aborts()
    capped()
    exhausted()
    rejected_path()
    accepted_path()
    round_trip()
    sweeping()
    says_what_it_is_doing()

    print()
    print("=" * 78)
    print("all checks passed" if not failures else f"{len(failures)} FAILED: {failures}")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
