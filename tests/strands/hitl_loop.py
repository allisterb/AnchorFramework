"""`src/agent/hitl.py`: the loop that puts a person at the one boundary with no oracle.

Nine scenarios, and every one of them runs with a SCRIPTED person. That is the design decision
this file exists to hold onto: a loop that can only be driven by somebody sitting at a terminal is
a loop nothing can test, and this one has branches -- a gate that fires, an answer that gives up,
an allowance that runs out, a person who overrules a model -- that would otherwise have to be
reproduced by hand every time anything changed.

  1. THE SHAPE THAT RUNS IS STILL THE SHAPE THAT WAS CHECKED. `hitl` adds one node to the graph,
     so `AlwaysReports` has to be re-proved over the graph `build_hitl` actually returns -- not
     inherited from the `auto` graph it is no longer identical to. Five exclusive decisions now,
     and still no half-decision and no undeclared assumption.
  2. THE PERSON IS NEVER SHOWN TLA+. The whole point is that they refine a REQUIREMENT; a question
     quoting a module at somebody who did not write one is a defect, and only the transcript of
     what was shown can catch it.
  3. THE QUESTION COMES FROM THE GATE THAT FIRED, and asking about the wrong one costs a whole
     attempt. Checked per gate, including the ordering that matters: a policy that refuses
     everything fails mutation scoring too, and "why does nothing catch a broken policy" is
     unanswerable while the real answer is "the session is missing a prior approval".
  4. WHAT NO CLARIFICATION CAN FIX IS NOT ASKED ABOUT. A model that cannot be reached, a policy
     that will not parse, a bug in Anchor -- rephrasing solves none of them, and asking anyway
     spends a person's attention on a 404.
  5. THE ANSWERS REACH THE DRAFTER, appended to the brief and never substituted for it. The
     original text has to survive verbatim, because it is what the reviewing gate compares
     against and what an auditor reads first.
  6. THE CHECKPOINT BEFORE THE CHECKS. A property can be well-formed, discriminating and agreed to
     by a second model and still be about the wrong rule. The person is shown what it forbids
     BEFORE TLC runs, and saying no stops the run -- with a report.
  7. EVERY EXIT REPORTS. Passing, giving up, running out, and the model being unreachable: four
     ways to leave, four session reports, and each says which it was.
  8. WHERE THE REQUIREMENT COMES FROM, and that a wrong guess is worse than a question. An
     `intents.md` beside a policy SET states one requirement per heading and none of them names
     the file; taking the first would spend a session -- model calls, TLC, a person's attention --
     on a requirement nobody chose.
  9. AND IT REFUSES TO RUN WITHOUT A PERSON, which `isatty` alone does not achieve on Windows.
     Answered in a subprocess, because the answer depends on what stdin IS.

No provider and no credentials.

    python tests/strands/hitl_loop.py
"""

from __future__ import annotations

import contextlib
import inspect
import io
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from anchor_workflow import check_intent                               # noqa: E402
from pipeline_run import BAD, GOOD, agent, scripted                    # noqa: E402
from translator.strands_graph_to_tla import to_tla                     # noqa: E402

from agent import hitl, pipeline                                       # noqa: E402

POLICIES = REPO / "tests" / "policies"
BRIEF = "SSH from the local range is permitted, and every external source is denied."

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)
        if detail:
            print(f"          {detail[:400]}")


def session(person: hitl.Scripted, out: Path, *, draft=GOOD, reviewer=None, policy="firewall.dw",
            refinements: int = 3, rounds: int = 1, mutants: int = 2):
    """One whole `hitl` session against scripted everything."""
    def graph(run):
        return hitl.build_hitl(
            run, person,
            drafter=draft if hasattr(draft, "model") else agent(draft, "draft"),
            answerer=agent("The property held.", "answer"),
            reviewer=reviewer or agent("VERDICT: MATCH -- it says the same.", "review"))

    return hitl.refine(POLICIES / policy, BRIEF, person, out=out, refinements=refinements,
                       build_graph=graph, mutants=mutants, rounds=rounds)


# -------------------------------------------------------------------------------------------
def same_object() -> None:
    """`hitl` is a DIFFERENT graph, so its properties are re-proved rather than inherited."""
    print("\nThe shape that runs is still the shape that was checked")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent=BRIEF, out=Path(tmp))
        graph = hitl.build_hitl(run, hitl.Scripted(), drafter=agent(GOOD, "draft"),
                                answerer=agent("ok", "answer"),
                                reviewer=agent("VERDICT: MATCH", "review"))

        t = to_tla(graph)
        check("the person's checkpoint is a fifth exclusive decision", len(t.exclusive) == 5,
              str(t.exclusive))
        check("no half-decisions", t.unpaired == [], str(t.unpaired))
        check("no undeclared assumptions", t.assumptions == [], str(t.assumptions))

        for name, a, b in t.exclusive:
            print(f"    {name:<10} accept {a}   reject {b}")

        holds, output = check_intent(t.tla)
        check("AlwaysReports HOLDS on the hitl graph that actually runs", holds,
              "\n".join(output.splitlines()[-8:]))

        # And `auto` is untouched: an extra node there would change the shape four properties were
        # chosen against, which is the whole point of having chosen it.
        plain = to_tla(pipeline.build(run, drafter=agent(GOOD, "d2"), answerer=agent("ok", "a2"),
                                      reviewer=agent("VERDICT: MATCH", "r2")))
        check("...and the auto graph still has exactly four", len(plain.exclusive) == 4,
              str(plain.exclusive))


def never_tla() -> None:
    """The person refines a REQUIREMENT. Nobody asks them to read a module."""
    print("\nThe person is never shown TLA+")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        # A draft the static gate turns away, twice, so the questions actually get asked.
        person = hitl.Scripted("ports 22 and 23, from the local range only", "stop")
        s = session(person, Path(tmp), draft=BAD, refinements=2)

        seen = "\n".join(person.shown + person.asked)
        print(f"  {len(person.asked)} question(s), {len(person.shown)} thing(s) shown")
        for q in person.asked:
            print(f"    Q: {q[:90]}")

        check("the person was asked something", len(person.asked) >= 1, str(person.asked))
        formal(seen, "when a gate rejects the draft")

        # EVERY STAGE ANNOUNCES ITSELF, because otherwise nothing does until the first question.
        # Found by running it for real: on a six-field policy the wait between the command and the
        # first prompt is minutes of model calls and TLC runs, and it printed nothing at all --
        # indistinguishable from a hang. `auto` reports each policy as it lands for exactly this
        # reason; the interactive mode, where somebody is actually sitting there, did not.
        # `score` and beyond are not reached here — this draft is turned away at preflight, so
        # they are checked in `the_checkpoint`, which gets that far.
        for stage in ("describe", "draft", "preflight"):
            check(f"`{stage}` says it has started",
                  any(f"  {stage:<10}" in t and "..." in t for t in person.shown),
                  str([t for t in person.shown if stage in t][:2]))
        check("...and says how long it took",
              any(t.startswith("\r  describe") and "s" in t for t in person.shown),
              str([t for t in person.shown if "describe" in t][:2]))
        check("and the session still ended with a report", s.runs != [], str(s.stopped))


# The tokens that mean the wrong document reached the person. Not a style rule: the gates talk to
# the DRAFTER, and their complaints are exactly right for it -- "the .cfg names INVARIANT X, which
# the module does not define. TLC stops with an error" is the sentence that gets the next round
# fixed. Forwarded to somebody who was asked for a requirement in English, it is a demand that they
# debug a file they have never seen, and it is what this scan caught on the first run.
FORMAL = ("MODULE", "INVARIANT", "EXTENDS", "/\\", "\\A ", "SPECIFICATION", ".tla", ".cfg",
          "TLA+", "TLC", "VARIABLE", "==", "|->")


def formal(text: str, where: str) -> None:
    for token in FORMAL:
        check(f"nothing shown to the person {where} mentions `{token}`", token not in text,
              next((line for line in text.splitlines() if token in line), ""))


def per_gate() -> None:
    """The question comes from the gate that fired, and the order is the diagnosis."""
    print("\nWhich question, and why that one")
    print("-" * 78)

    def asked(**state) -> hitl.Ask | None:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent=BRIEF, out=Path("."))
        for k, v in state.items():
            setattr(run, k, v)
        return hitl.ask_about(run)

    # --- the static gate, on the claim that cannot fail -----------------------------------------
    a = asked(rejected_at="preflight", complaints=["Claim cannot fail. It is already true in all "
                                                   "6 state(s) it ranges over"])
    check("a claim that cannot fail asks which VALUES to check at",
          a is not None and "which exact values" in a.question.lower(),
          a.question if a else "none")

    # --- the mutation gate ----------------------------------------------------------------------
    a = asked(rejected_at="score", complaints=["the property HOLDS, but it also holds of every "
                                               "broken version of this policy that was tried"])
    check("a property that catches no mutant asks what must NEVER be allowed",
          a is not None and "never allow" in a.question.lower(), a.question if a else "none")
    # AND WHAT MUST BE ALLOWED, which is the half that actually catches a mutant. Every mutation
    # tried removes or narrows a permission, so a refusal-only property survives all of them — and
    # asking only for a refusal, as this did, is a question that induces exactly the property the
    # gate then rejects. Three live sessions went round that loop.
    check("...and ALSO what it must allow, which is the half a mutant can break",
          a is not None and "must allow" in a.question.lower(), a.question if a else "none")
    check("...and says why, so the answer is not a guess",
          a is not None and "takes permissions AWAY" in a.said, a.said if a else "none")

    # --- the decision probe, and it must OUTRANK the mutation gate ------------------------------
    # Both fire together whenever the policy refuses everything the property names, and only one
    # of them has an answer a person can give: "what would a broken policy do" is unanswerable
    # while the real defect is a missing prior approval.
    a = asked(rejected_at="score", decision="constant",
              complaints=["the property HOLDS, but it also holds of every broken version"])
    check("a policy that refuses everything asks what must have happened FIRST",
          a is not None and "before" in a.question.lower(), a.question if a else "none")
    check("...even though the mutation gate is what rejected it",
          a is not None and a.gate == "the policy's decision", a.gate if a else "none")

    # --- the round trip -------------------------------------------------------------------------
    a = asked(rejected_at="review", review="mismatch", explained="No request may be granted.",
              review_said="VERDICT: MISMATCH -- the requirement is about refunds.")
    check("a mismatch shows the person BOTH texts and asks which is right",
          a is not None and "refunds" in a.said and "No request may be granted" in a.said,
          a.said if a else "none")
    check("...and tells them they may overrule the reviewing model",
          a is not None and "keep" in a.question.lower(), a.question if a else "none")

    # --- rounds exhausted, with the vocabulary shown --------------------------------------------
    a = asked(exhausted=True, vocab={"actions": ["Connect"],
                                     "inputFields": [{"name": "port",
                                                      "domain": ["Num(22)", "Num(23)"]}]})
    check("an exhausted allowance asks for the requirement again",
          a is not None and "requirement again" in a.question.lower(), a.question if a else "none")
    check("...and shows the policy's own vocabulary, untagged",
          a is not None and "port: 22, 23" in a.hint and "Num(" not in a.hint,
          a.hint if a else "none")


def nothing_to_ask() -> None:
    """What no clarification can fix is not put to a person."""
    print("\nWhat is not the person's to fix")
    print("-" * 78)

    def asked(**state) -> hitl.Ask | None:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent=BRIEF, out=Path("."))
        for k, v in state.items():
            setattr(run, k, v)
        return hitl.ask_about(run)

    check("an unreachable model is not a question for the person",
          asked(unreachable=["draft: 404 model not found"]) is None)
    check("nor is a bug in Anchor", asked(crashed=["check failed: division by zero"]) is None)
    check("nor is a policy that cannot be read", asked(rejected_at="describe") is None)

    # NOR A MODULE THAT COMPILED AND THEN DIED EVALUATING. Almost always the tagging discipline --
    # `x = 1` against a `Num(1)` -- which is a fault in the drafter's TLA+ that no restatement of a
    # requirement in English can reach. A live run asked somebody to say their requirement again,
    # right after they had answered it well, for a fault their words had nothing to do with. The
    # cause was upstream: `author.assess` reported every no-verdict as "did not compile", so the
    # two were indistinguishable here.
    check("nor a module that compiled but could not be evaluated",
          asked(rejected_at="score",
                complaints=["the module compiled but could not be evaluated, so nothing was "
                            "checked:\nError: Attempted to check equality of integer 1 with "
                            "non-integer"]) is None)
    # ...and the one it IS still asked about, so the two are not collapsed again.
    failed_parse = asked(rejected_at="score",
                         complaints=["the module did not compile, so nothing was checked:\n"
                                     "Parse Error at line 12"])
    check("...but a module that did not COMPILE still asks for the requirement again",
          failed_parse is not None and failed_parse.gate == "drafting",
          str(failed_parse))

    # And the loop STOPS on those rather than going round again spending a model call per attempt.
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        person = hitl.Scripted("more detail", "more detail", "more detail")
        s = session(person, Path(tmp), policy="does_not_exist.dw", refinements=3)
        check("an unreadable policy ends the session after ONE attempt", len(s.runs) == 1,
              str(len(s.runs)))
        check("...without asking the person anything", person.asked == [], str(person.asked))
        check("...and says why it stopped rather than that it failed",
              "nothing a clarification can fix" in s.stopped, s.stopped)

        # NO QUESTIONS IS NOT A PASS, and reading one as the other is what the first live run
        # produced: "the first attempt passed every gate", directly above a table saying no
        # property was produced. Nobody was asked because there was nothing a person could answer.
        report = hitl.transcript(s)
        check("...and the session report does NOT call that passing",
              "passed every gate" not in report and "did not pass" in report, report[:600])


def answers_reach_the_drafter() -> None:
    """Appended to the brief, never substituted for it."""
    print("\nWhat the person says becomes part of the requirement")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        # Rejected the first time, fine the second: so there is a question, an answer, and a second
        # attempt whose drafter can be inspected.
        drafter = scripted("draft", BAD, GOOD, GOOD)
        person = hitl.Scripted("ports 22 and 23, and only from the local range", "y")
        s = session(person, Path(tmp), draft=drafter, refinements=3)

        print(f"  {len(s.runs)} attempt(s), {len(s.clarifications)} clarification(s), "
              f"passed={s.passed}")
        check("it took two attempts", len(s.runs) == 2, str(len(s.runs)))
        check("the person's answer was recorded", len(s.clarifications) == 1,
              str(s.clarifications))

        intent = s.runs[-1].intent
        check("the ORIGINAL brief survives verbatim", BRIEF in intent, intent[:200])
        check("...with the answer appended, not substituted",
              "ports 22 and 23" in intent and intent.index(BRIEF) < intent.index("ports 22"),
              intent[:400])

        # The drafter is the thing that has to see it; everything else is bookkeeping.
        second = drafter.model.prompts[1]              # type: ignore[attr-defined]
        check("and the DRAFTER saw it on the next attempt", "ports 22 and 23" in second,
              second[-400:])

        # AND WHAT THE LAST ATTEMPT WAS REJECTED FOR, so a gate need not say it twice.
        check("...along with what the previous attempt was rejected for",
              "rejected" in second.lower() and "OutsideIsRefused" in second, second[-600:])

        # It reaches the REPORT too: a requirement assembled over two rounds is a different
        # artifact from one that arrived whole, and findings.md is where that has to be visible.
        text = s.runs[-1].findings.read_text(encoding="utf-8")
        check("findings.md says a person was asked", "A person was asked about this requirement"
              in text, text[:600])
        check("...and quotes what they said", "ports 22 and 23" in text, text[:600])


def the_checkpoint():
    """What the claim forbids, put to the person BEFORE anything is checked.

    Returns the session that PASSED, for `every_exit_reports` to read. A second passing session
    would be a second mutation-scoring pass -- eight TLC runs -- for a transcript that says the
    same thing, and this harness is already the longest single test in its class.
    """
    print("\nThe checkpoint before the checks")
    print("-" * 78)

    # --- the person confirms --------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        person = hitl.Scripted("y")
        passing = s = session(person, Path(tmp))

        check("the session passed", s.passed, s.stopped)
        check("the person was shown what the claim forbids",
              any("what the claim will forbid" in t for t in person.shown), str(person.shown[:3]))
        check("...before anything was checked", s.runs[-1].confirmed is True)

        # AND THE READING ITSELF IS STILL ENGLISH. This is the one place a module's own text is
        # deliberately put in front of somebody, and `explain` is what keeps it readable -- so if
        # its rendering ever starts leaking the formalism, this is where it shows.
        print("\n".join(f"    | {line}" for line in
                        "\n".join(person.shown).strip().splitlines()[:12]))
        formal("\n".join(person.shown), "at the checkpoint")

        # ...and nothing was LOST making it readable. A transform that quietly dropped a claim
        # would be worse than one that left a `|->` in: the person would confirm a reading of half
        # the property, and the report would record it as a confirmation of all of it.
        shown = "\n".join(person.shown)
        missing = [line for line in hitl.readable(s.runs[-1].explained).splitlines()
                   if line.strip() and line.strip() not in shown]
        check("every line of the reading reached the person", missing == [], str(missing[:2]))

        # The two long stages announce themselves too. `score` is most of the wait on a real
        # policy — one TLC run per mutant — and is the one most easily mistaken for a hang.
        for stage in ("score", "review", "confirm"):
            check(f"`{stage}` says it has started",
                  any(f"  {stage:<10}" in t and "..." in t for t in person.shown),
                  str([t for t in person.shown if stage in t][:2]))

        text = s.runs[-1].findings.read_text(encoding="utf-8")
        check("findings.md records the confirmation",
              "confirmed it is what they meant" in text, text[:900])
        check("...and says the person did NOT read the formal claim",
              "did not read the formal claim" in text, text[:900])
        # The claim the document is allowed to make changes, and only this far.
        check("...and the footer no longer calls it an unattended run",
              "is still not a person having written the property" in text, text[-500:])

    # --- the person says no -------------------------------------------------------------------
    # THE SCENARIO THE WHOLE CHECKPOINT EXISTS FOR: every gate passed, a second model agreed, and
    # the property is about the wrong rule. Nothing else in the pipeline can catch this.
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        # ONE attempt. What is being checked is what a `no` does to the run it is said in, and a
        # second attempt would buy another mutation-scoring pass -- eight TLC runs -- to re-observe
        # the same rejection.
        person = hitl.Scripted("n", "it says nothing about port 23, which is the one I care about")
        s = session(person, Path(tmp), refinements=1)

        first = s.runs[0]
        check("the person's `no` stops the run", first.rejected_at == "confirm",
              first.rejected_at)
        check("...and it is not reported as a draft being rejected",
              pipeline.outcome(first) == "the person said this is not what they meant",
              pipeline.outcome(first))
        check("what they said became a clarification",
              any("port 23" in a for _, a in s.clarifications), str(s.clarifications))

        text = first.findings.read_text(encoding="utf-8")
        check("findings.md says the gate was the PERSON'S, not a criterion in code",
              "The gate below is the PERSON'S" in text, text[:1200])
        check("...and that no tool disagreed with the draft",
              "No tool disagreed with the draft" in text, text[:1200])

    return passing


def every_exit_reports(passing) -> None:
    """Four ways to leave a session, and each says which it was."""
    print("\nEvery exit reports")
    print("-" * 78)

    # --- the person gives up --------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        person = hitl.Scripted("stop")
        s = session(person, Path(tmp), draft=BAD, refinements=3)
        check("a person who gives up ends the session there", len(s.runs) == 1, str(len(s.runs)))
        check("...and it is recorded as their choice", s.stopped == "the person ended the session",
              s.stopped)
        report = hitl.transcript(s)
        check("the session report says so", "the person ended the session" in report, report[-400:])

    # --- ...and gives up AT THE CHECKPOINT, which is a different exit ----------------------------
    # A `no` followed by nothing leaves the brief unchanged, so a further attempt would re-draft
    # from the same text and put the identical reading in front of them, once per attempt left.
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        person = hitl.Scripted("n", "stop")
        s = session(person, Path(tmp), refinements=3)
        check("saying no and then nothing also ends the session", len(s.runs) == 1,
              str(len(s.runs)))
        check("...rather than asking the same thing again",
              s.stopped == "the person ended the session", s.stopped)
        check("...and nothing was recorded as a clarification", s.clarifications == [],
              str(s.clarifications))

    # --- the allowance runs out -----------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        person = hitl.Scripted("more detail", "more detail", "more detail", "more detail")
        s = session(person, Path(tmp), draft=BAD, refinements=2)
        check("the allowance bounds the session", len(s.runs) == 2, str(len(s.runs)))
        check("...and running out is not a crash", "allowance" in s.stopped, s.stopped)

        report = hitl.transcript(s)
        print("\n".join(f"    {line}" for line in report.splitlines()[-9:]))
        rows = [line for line in report.splitlines() if line.startswith("| ") and line[2].isdigit()]
        check("the session report has a row per attempt", len(rows) == 2, str(rows))
        check("...and does not end by claiming it passed",
              "did not end by passing" in report, report[-500:])
        # BEING IN `hitl` IS NOT A CONFIRMATION. Nobody reached the checkpoint in this session --
        # every attempt was rejected before it -- so a footer crediting the person with confirming
        # a reading would be claiming the strongest thing in the document on the strength of the
        # mode it was run in. It did exactly that until this check was written.
        check("...and does not credit the person with confirming anything",
              "Nothing here was confirmed by the person" in report
              and "confirmed a plain-English reading" not in report, report[-500:])

    # --- it passes ------------------------------------------------------------------------------
    report = hitl.transcript(passing)
    check("a session that passed says the person was asked nothing",
          "asked nothing" in report, report[:500])
    check("...and reports what it cost", "tokens** over" in report, report[-600:])
    # THE CLAIM THE WHOLE MODE IS ALLOWED TO MAKE. If this ever has to change because the wording
    # got stronger, that is precisely the defect it exists to catch.
    check("...and does not claim a person verified anything",
          "is still not a person having written the property" in report
          and "verified by a human" not in report, report[-500:])


def refuses_without_a_person() -> None:
    """The guard that makes `hitl` a mode and not an expensive way to talk to nobody.

    IT FAILED ONCE, MEASURABLY. `isatty` is the CRT's `_isatty` on Windows and `_isatty` is true
    for any CHARACTER DEVICE -- `NUL` is one -- so `hitl policy.dw < NUL` passed the guard, called
    three models, ran TLC, and then read EOF as the answer to the confirm question. 30,893 tokens.
    `at_a_terminal` asks `GetConsoleMode` instead, which is the test CPython itself uses.

    A SUBPROCESS, because this cannot be faked from inside the process asking: the answer is a
    property of the stdin handle the OS gave us. The positive direction -- a real console answering
    true -- is not reachable from a test runner, which never has one; it was checked by hand by
    installing a `CONIN$` handle as stdin, and `GetConsoleMode` answering true for `CONIN$` and
    false for `NUL` is what the function rests on.
    """
    print("\nRefusing to run without a person")
    print("-" * 78)

    probe = (f"import sys; sys.path.insert(0, {str(REPO / 'src')!r}); "
             "from agent.hitl import at_a_terminal; print(at_a_terminal())")

    for label, kw in (("redirected from NUL", {"stdin": subprocess.DEVNULL}),
                      ("a pipe", {"input": ""})):
        done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, **kw)
        check(f"stdin {label}: no person here", done.stdout.strip() == "False",
              done.stdout.strip() + done.stderr[-200:])

    # And that the guard is WIRED, which the function being right does not establish.
    source = inspect.getsource(hitl.main)
    check("main asks at_a_terminal", "at_a_terminal()" in source)
    check("and not isatty directly", "sys.stdin.isatty()" not in source, source[:200])


def where_the_requirement_comes_from() -> None:
    """The brief can come out of the file `auto` already sweeps, and nothing may be guessed.

    NO PROVIDER AND NO GRAPH: this is the step before either, and it is all text and files. What it
    protects is the difference between the two modes at this exact point. `auto` must fail when no
    requirement is stated, because there is nobody to ask; `hitl` must ASK, because there is -- and
    must ask rather than pick, because a session started on the wrong requirement looks exactly
    like a session started on the right one until it ends.
    """
    print("\nWhere the requirement comes from")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-intents-") as tmp:
        here = Path(tmp)
        policy = here / "firewall.dw"
        policy.write_text((POLICIES / "firewall.dw").read_text(encoding="utf-8"), encoding="utf-8")
        intents = here / "intents.md"

        person = hitl.Scripted()
        check("no intents file: nothing stated, and nothing said about it",
              hitl.stated_intent(policy, None, person) is None and person.shown == [],
              str(person.shown))

        intents.write_text(f"# Intents\n\n## firewall.dw\n\n> {BRIEF}\n", encoding="utf-8")
        person = hitl.Scripted()
        check("a heading naming the policy is taken",
              hitl.stated_intent(policy, None, person) == BRIEF)
        check("shown rather than used silently", any(BRIEF in line for line in person.shown),
              str(person.shown))
        check("and nothing was asked", person.asked == [], str(person.asked))

        # The other shape an intents file takes: one policy SET, a requirement per heading, not one
        # of them the filename. This is `examples/aws2`.
        intents.write_text(f"# Intents\n\n## inbound.dw\n\n> {BRIEF}\n\n"
                           "## outbound.dw\n\n> Nothing may leave the network.\n", encoding="utf-8")
        person = hitl.Scripted("outbound")
        check("several headings and none names it: the person chooses",
              hitl.stated_intent(policy, None, person) == "Nothing may leave the network.")
        check("having been shown every one of them",
              all(any(h in line for line in person.shown) for h in ("inbound.dw", "outbound.dw")),
              str(person.shown))
        check("asked once, and nothing guessed", len(person.asked) == 1, str(person.asked))
        formal("\n".join(person.shown + person.asked), "choosing a requirement")

        # A name is a convenience, not a grammar: anything that is not one is the requirement.
        person = hitl.Scripted("Only port 22, and only from inside.")
        check("prose instead of a name is the requirement itself",
              hitl.stated_intent(policy, None, person) == "Only port 22, and only from inside.")

        # And walking away has to stay available here, exactly as at the open question.
        person = hitl.Scripted("stop")
        check("a stop word survives to main, which reads it as giving up",
              hitl.stated_intent(policy, None, person) in hitl.STOP_WORDS)

        # An absent default says nothing; an absent file somebody NAMED is a typo.
        try:
            hitl.stated_intent(policy, here / "nope.md", hitl.Scripted())
            check("an intents file named and missing stops the run", False)
        except SystemExit as stopped:
            check("an intents file named and missing stops the run", stopped.code == 2,
                  str(stopped.code))


def hitl_is_not_auto() -> None:
    """`auto` must be untouched by all of this: no questions, no person, the same eight stages.

    STRUCTURAL RATHER THAN A RUN, because `tests/strands/pipeline_run.py` already runs the auto
    graph end to end and asserts that every stage executed. Repeating it here would buy one more
    mutation-scoring pass -- eight TLC runs -- to re-observe a fact next door, and what this file
    adds is only whether the `confirm` parameter leaked into the default.
    """
    print("\nAuto is unchanged")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-hitl-") as tmp:
        run = pipeline.Run(policy=POLICIES / "firewall.dw", intent=BRIEF, out=Path(tmp), mutants=2)
        graph = pipeline.build(run, drafter=agent(GOOD, "draft"), answerer=agent("ok", "answer"),
                               reviewer=agent("VERDICT: MATCH", "review"))

        print(f"  {len(graph.nodes)} node(s): {', '.join(sorted(graph.nodes))}")
        check("no confirm node in the auto graph", "confirm" not in graph.nodes,
              str(sorted(graph.nodes)))
        check("and the auto stages are exactly what they were",
              set(graph.nodes) == set(pipeline.STAGES), str(sorted(graph.nodes)))
        check("nothing was confirmed", run.confirmed is False)
        check("and nothing was clarified", run.clarifications == [], str(run.clarifications))

        # The footer, from the report stage directly: what it claims turns on `run.confirmed`, and
        # nothing upstream of that needs to run to settle which sentence comes out.
        pipeline.stage_report(run, "")
        text = run.findings.read_text(encoding="utf-8") if run.findings else ""
        check("the auto footer is the unattended one",
              "weaker evidence than findings against one a person wrote" in text, text[-400:])


def says_what_it_will_do() -> None:
    """`main` checks the LLM before the person is asked anything, then says what it will run.

    Run through `main` itself, with the terminal check answered yes, a scripted person, and
    `refine` stopped at its door -- so no graph is built and no model is called.
    """
    print("\nSaying what it will do, before it does it")
    print("-" * 78)
    from agent import policy_agent

    class Stopped(Exception):
        pass

    def stop(*_a, **_k):
        raise Stopped

    saved = (hitl.at_a_terminal, hitl.Terminal, hitl.refine, policy_agent.readiness)
    person = hitl.Scripted()
    hitl.at_a_terminal, hitl.Terminal, hitl.refine = (lambda: True), (lambda: person), stop
    try:
        policy_agent.readiness = lambda *a, **k: policy_agent.Readiness(
            "gemini", "x", problems=["no Gemini API key: (stand-in)"])
        sys.argv = ["hitl.py", str(POLICIES / "firewall.dw")]
        with contextlib.redirect_stderr(io.StringIO()):
            code = hitl.main()
        check("an LLM that cannot be built stops hitl before the person is asked, exit 3",
              code == 3 and person.asked == [], f"{code} {person.asked}")

        policy_agent.readiness = lambda *a, **k: policy_agent.Readiness(
            "gemini", "stand-in", source="none (scripted)", model_source="scripted")
        sys.argv = ["hitl.py", str(POLICIES / "firewall.dw"), "--intent", BRIEF]
        try:
            hitl.main()
        except Stopped:
            pass
        shown = "\n".join(person.shown)
        check("the session is described before it starts",
              "with you as one of the gates" in shown and "from --intent:" in shown
              and "confirm (you)" in shown and "stand-in via gemini" in shown, shown[:900])
        formal(shown, "in the summary before a session")

        # AND AT THE END, a broken property as the person reads it: `sentence()` quotes the TLA+
        # value that breaks the claim, which is what `auto` and the audit print and this may not.
        from checker.witness import Confirmation
        run = pipeline.Run(policy=POLICIES / "firewall_open.dw", intent=BRIEF, out=Path("."))
        run.module_path, run.rules = Path("Intent.tla"), {"rules": [], "defects": []}
        run.prop = {"held": False, "violations": [{"invariant": "OutsideIsRefused",
                                                   "state": {"req": "[port |-> 22]"}}]}
        run.witness = [Confirmation(invariant="OutsideIsRefused", state={"req": "[port |-> 22]"},
                                    demanded=False, engine="allow", agreed=True, at=1)]
        ending = "\n".join(pipeline.closing(run, plain=True))
        check("the end of a session gives a broken verdict in plain words",
              "the Dogwood engine ALLOWS a session your requirement says it must REFUSE" in ending,
              ending)
        formal(ending, "in the verdict at the end of a session")
    finally:
        hitl.at_a_terminal, hitl.Terminal, hitl.refine, policy_agent.readiness = saved


def main() -> int:
    print("=" * 78)
    print("hitl: a person at the one boundary with no oracle behind it")
    print("=" * 78)

    same_object()
    never_tla()
    per_gate()
    nothing_to_ask()
    answers_reach_the_drafter()
    passing = the_checkpoint()
    every_exit_reports(passing)
    where_the_requirement_comes_from()
    refuses_without_a_person()
    says_what_it_will_do()
    hitl_is_not_auto()

    print()
    print("=" * 78)
    print("all checks passed" if not failures else f"{len(failures)} FAILED: {failures}")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
