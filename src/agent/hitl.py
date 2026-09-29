"""`hitl`: the same pipeline, but a person is one of the gates.

    python src/agent/hitl.py examples/aws1/07-trust-decay.dw \\
        --intent "After 15 minutes without advisor interaction, the agent loses write access."

WHY THIS EXISTS, and it is not "autonomy did not work". It is that autoformalisation has one step
with no oracle behind it. Everything downstream of a property module is mechanical -- does it
compile, does the decision vary, does it catch a mutant, does it hold -- and every one of those is
a criterion in code that cannot be talked out of its answer. Everything UPSTREAM is a person saying
what they meant, and no tool in this repo can check a property against an intention nobody wrote
down. A sweep over `agent-policy.dw` accepted one requirement in five, and the four that failed
failed on the semantic gate rather than on syntax: the drafts were well-formed statements of
something the brief did not quite say. That is the boundary the survey in `reference/README.md`
names as the place to put a human, and it is the only place this mode puts one.

WHAT THE PERSON IS ASKED IS NEVER TLA+. Each gate already knows exactly what went wrong, in terms
of the POLICY and the BRIEF rather than of the module -- "this claim is true before the policy is
consulted", "every request you named is refused", "a broken version of this policy passes too".
`ask_about` turns that into a question about the requirement, the person answers in prose, the
answer is appended to the brief, and the graph runs again. The person refines a requirement they
can read; nobody is asked to debug a module they did not write.

    brief ─> [ the graph ] ─> passed?  ─ yes ─> checked, and reported
               ^                 │
               │                 no
               │                 │
               └── clarify ──────┘        bounded by --refinements, and every exit reports

THE LOOP IS OUTSIDE THE GRAPH, for the same reason `stage_draft`'s retry is inside one node: a
retry is a cycle, and a cyclic graph is a graph neither `DependencyDAG` nor `StrandsGraph` can
express -- so everything proved in `tests/strands/anchor_workflow.py` would stop applying to it.
Here each attempt is one whole acyclic run of the shape that was checked, and the loop is ordinary
Python around it. `AlwaysReports` holds of every attempt rather than of the session, which is
strictly more than it would hold of a cyclic one.

THE I/O IS INJECTED, and that is load-bearing rather than tidy. A loop that can only be driven by a
person sitting at a terminal is a loop nothing can test, and this one has branches -- a gate that
fires, an answer that gives up, an allowance that runs out -- a person would otherwise have to
reproduce by hand every time. `Console` is three methods; `tests/strands/hitl_loop.py` drives the
whole mode with a scripted one and no provider at all. Which renderer the terminal uses is then a
choice that costs nothing to change.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# policy_agent's module level is stdlib only -- `mcp` and `strands` are imported inside the
# functions that need them -- so naming it here costs nothing at import time.
from agent import pipeline, policy_agent                               # noqa: E402
from agent.pipeline import Run, gate, outcome                          # noqa: E402

STOP_WORDS = {"", "stop", "quit", "exit", "give up", "nothing", "done"}


# ------------------------------------------------------------------------------------------------
# The seam
# ------------------------------------------------------------------------------------------------
class Console:
    """Everything this mode does to a person, in three methods.

    Deliberately this small. The loop's job is to ask one question at a time and read one answer,
    and a richer surface would be a richer thing to reimplement for the scripted stand-in -- which
    is the implementation that has to keep working, because it is the one the tests use.
    """

    def say(self, text: str = "", *, newline: bool = True) -> None:
        raise NotImplementedError

    def ask(self, question: str, *, hint: str = "") -> str:
        raise NotImplementedError

    def confirm(self, question: str, *, default: bool = True) -> bool:
        raise NotImplementedError


def at_a_terminal() -> bool:
    """Is there a person on the other end of stdin? NOT what `isatty` answers on Windows.

    CPython's `isatty` is the CRT's `_isatty` there, and `_isatty` is true for any CHARACTER
    DEVICE. `NUL` is a character device. So `anchor hitl policy.dw < NUL` -- which is how a
    service, a scheduled task or a CI step launches a process it does not intend to talk to --
    passed the guard below, drafted, scored, reviewed, and then read EOF as the answer to the
    confirm question. 30,893 tokens, to nobody.

    `GetConsoleMode` is the question actually worth asking: it succeeds on a console handle and
    fails on every other kind, NUL included. Asked only after `isatty` has said yes, because a pipe
    and a redirected file are reported correctly by `isatty` on both platforms and there is nothing
    for this to add there.

    CHECKED IN BOTH DIRECTIONS, on a real console handle rather than by reading the documentation:
    `GetConsoleMode` answers true for `CONIN$` (mode 503) and false for `NUL`. It is also the test
    CPython itself uses to decide whether a stream is a Windows console, in `_io._WindowsConsoleIO`.
    `GetConsoleWindow` is NOT usable for this and was tried: it answers false under a ConPTY that
    has a perfectly good console.

    WHAT STILL REFUSES, and did before this too: an interactive mintty -- git bash -- where stdin
    is a pipe to the pty and `isatty` is already false. Run the mode from a console host.

    The fallback on a missing `ctypes` or `kernel32` is to believe `isatty`. That is the behaviour
    this replaced, so a Python without ctypes is no worse off than before rather than unable to run
    the mode at all.
    """
    if not sys.stdin.isatty():
        return False
    if sys.platform != "win32":
        return True

    try:
        import ctypes                                                   # noqa: PLC0415
        from ctypes import wintypes                                     # noqa: PLC0415

        kernel32 = ctypes.windll.kernel32
        # DECLARED, not left to default. ctypes assumes c_int, and a HANDLE is pointer-sized -- an
        # undeclared GetStdHandle truncates on 64-bit and the truncated value is then asked about.
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

        mode = wintypes.DWORD()
        # -10 is STD_INPUT_HANDLE: the process's own, which is what a redirect replaces, rather
        # than anything derived from `sys.stdin`.
        return bool(kernel32.GetConsoleMode(kernel32.GetStdHandle(-10), ctypes.byref(mode)))
    except (AttributeError, OSError, ValueError):
        return True


class Terminal(Console):
    """stdlib `print` and `input`, wrapped to the width of a paragraph.

    NO DEPENDENCY, on purpose and for now. Everything this class does is one call each; swapping it
    for a renderer with colour, a spinner over the TLC runs and syntax highlighting is a change to
    this class and to nothing else -- which is the reason the seam is here, rather than the reason
    it is currently empty.

    IT WRITES TO stderr, because stdout carries the one machine-readable thing this mode emits: the
    path of the session report. A caller doing `where=$(anchor hitl ...)` must not collect the
    conversation as well.
    """

    def __init__(self, width: int = 92, stream=None) -> None:
        self.width, self.stream = width, stream or sys.stderr

    def say(self, text: str = "", *, newline: bool = True) -> None:
        # WRAPS ONLY WHAT IS TOO LONG, and keeps the indent. The reading of a claim arrives already
        # laid out -- a claim name, then `says` / `forbids` / `applies` lines indented under it --
        # and re-flowing every line to the width turned that into a paragraph of run-on prose.
        out = []
        for line in str(text).split("\n"):
            if not line.strip() or len(line) <= self.width:
                # NOT rstripped. A progress line overwrites a longer one by returning to column 0
                # and painting over it, and the trailing spaces that do the painting are exactly
                # what a tidy-up would remove -- leaving the tail of "asking the model ..." sitting
                # after the elapsed time.
                out.append(line if line.strip() else "")
            else:
                indent = " " * (len(line) - len(line.lstrip()))
                # NEITHER HYPHENS NOR LONG WORDS ARE BREAK POINTS. Both defaults are wrong for what
                # this prints: a findings.md path wrapped as `...anchor\hitl-` / `identity\...` is
                # no longer a path anybody can copy, and `hitl-identity` is one word to a reader
                # even though textwrap sees two.
                out.append(textwrap.fill(line, self.width, initial_indent=indent,
                                         subsequent_indent=indent + "  ",
                                         break_on_hyphens=False, break_long_words=False))
        # `newline=False` leaves the cursor on the line, so the next call can overwrite it with a
        # leading `\r` -- which is how a stage says it has STARTED and then says how long it took,
        # on one line instead of two.
        print("\n".join(out), file=self.stream, end="\n" if newline else "")
        self.stream.flush()

    def ask(self, question: str, *, hint: str = "") -> str:
        self.say()
        self.say(question)
        if hint:
            self.say(f"({hint})")
        try:
            return input("> ").strip()
        except EOFError:
            # NOT an empty answer, though it arrives looking like one. End of input means nobody is
            # there -- a pipe, a closed terminal, a runner -- and the loop must stop rather than
            # read silence as "I have nothing to add" and go round again asking a wall.
            self.say("(no more input)")
            return "stop"

    def confirm(self, question: str, *, default: bool = True) -> bool:
        said = self.ask(f"{question} [{'Y/n' if default else 'y/N'}]").lower()
        return default if not said else said.startswith("y")


class Scripted(Console):
    """A person who has already decided what to say. The stand-in the harness drives.

    Records everything it was SHOWN as well as everything it was asked, because half of what this
    mode has to get right is what reaches the person: a question that quotes TLA+ at somebody who
    did not ask for TLA+ is a defect, and only the transcript can catch it.
    """

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.shown: list[str] = []
        self.asked: list[str] = []

    def say(self, text: str = "", *, newline: bool = True) -> None:
        self.shown.append(str(text))

    def ask(self, question: str, *, hint: str = "") -> str:
        self.asked.append(question)
        # OUT OF ANSWERS IS "STOP", never a hang and never a repeat of the last one. A scripted
        # person who runs dry is a person who has left, and the loop's exit on that is a branch
        # worth exercising rather than an accident worth avoiding.
        return self.answers.pop(0) if self.answers else "stop"

    def confirm(self, question: str, *, default: bool = True) -> bool:
        said = self.ask(question)
        return default if not said else said.lower().startswith("y")


# ------------------------------------------------------------------------------------------------
# What to ask, and it comes from the gate that fired
# ------------------------------------------------------------------------------------------------
@dataclass
class Ask:
    """One question for the person, and the finding it came from."""

    gate: str
    said: str               # what the gate found, in the policy's terms and never the module's
    question: str
    hint: str = ""


def vocabulary(run: Run) -> str:
    """The nouns this policy actually has, so an answer names things that exist.

    A person asked to be more concrete will reach for the domain's words rather than the policy's,
    and a requirement about "the finance team" against a policy that only knows `role` values
    `admin` and `user` produces another round of the same failure. Showing the vocabulary costs two
    lines and turns a vague answer into a nameable one.
    """
    v = run.vocab or {}
    lines = []
    if actions := v.get("actions"):
        lines.append("actions: " + ", ".join(str(a) for a in actions))
    for where in ("inputFields", "outputFields"):
        for f in v.get(where) or []:
            # `Num(22)` and `Str("local")` are the TLA+ constructors; a person reading this wants
            # 22 and local. Tagging is the module's business and never the person's.
            values = ", ".join(untag(str(d)) for d in (f.get("domain") or []))
            lines.append(f"{f.get('name')}: {values}" if values else str(f.get("name")))
    return "\n".join(f"  {line}" for line in lines)


RECORD = re.compile(r"\b\w+\s*=\s*\[([^\[\]]*?\|->.*?)\]", re.DOTALL)
DECISION_TERM = re.compile(r"\s*\((?:~\s*)?\w+\([^()]*\)\)")


def readable(explained: str) -> str:
    """`explain`'s reading, with the last of the formalism taken out of it.

    THE READING IS ALREADY ENGLISH, and that is what `explain` is for -- "whenever req.port is 22
    and req.origin is local, then the policy GRANTS it" needs nothing from this function. Two
    things in it are not: the states are printed as TLA+ records, `req = [port |-> 22, origin |->
    "external"]`, and each line ends with the decision term it was derived from, `(Grants(req))`.
    Both are useful in findings.md, which is a technical document read after the fact. Neither is
    useful to the person standing at the checkpoint, and `|->` in front of somebody who was asked
    for a requirement in English is the whole premise of this mode leaking.

    A PRESENTATION TRANSFORM OVER OUR OWN RENDERER, so it is allowed to know the shape -- but it
    substitutes rather than reconstructs, and anything it does not recognise passes through
    unchanged. Losing a line of the reading would be worse than leaving a parenthesis in it, and
    `tests/strands/hitl_loop.py` scans what actually reached the person rather than trusting this.
    """
    def fields(m: re.Match[str]) -> str:
        body = re.sub(r"\s+", " ", m.group(1))
        # PARENTHESISED, because these are listed several to a line. Without a bracket of some
        # kind, four states become "port 22, origin external, port 22, origin local, ..." -- one
        # undifferentiated list where there were four separate requests, which is a worse reading
        # than the record syntax it replaced.
        return "(" + ", ".join(
            f"{k.strip()} {untag(v.strip())}"
            for k, _, v in (pair.partition("|->") for pair in body.split(",")) if k.strip()) + ")"

    return DECISION_TERM.sub("", RECORD.sub(fields, explained)).strip()


def untag(value: str) -> str:
    """`Num(22)` -> `22`, `Str("local")` -> `local`. Anything else unchanged."""
    for prefix in ("Num(", "Str(", "Bool("):
        if value.startswith(prefix) and value.endswith(")"):
            value = value[len(prefix):-1]
            break
    return value.strip('"')


def ask_about(run: Run) -> Ask | None:
    """The question this attempt earned. `None` when there is nothing a person can fix.

    THE ORDER IS THE DIAGNOSIS. Several complaints can be true at once, and asking about the wrong
    one costs a whole attempt: a policy that refuses every request the property names will also
    fail mutation scoring, and "why does nothing catch a broken policy" is unanswerable while the
    real answer is "the session is missing a prior approval". So the most upstream cause is asked
    about first.

    AND `None` IS NOT A FAILURE OF THIS FUNCTION. A model that cannot be reached, a policy that
    will not parse, and a bug in Anchor are all things no clarification improves; asking a person
    to rephrase their way out of a 404 is worse than stopping.
    """
    # --- not the person's to fix ---------------------------------------------------------------
    if run.unreachable or run.crashed or run.rejected_at == "describe":
        return None

    # --- already asked, inside the run ---------------------------------------------------------
    if run.rejected_at == "confirm":
        return None

    # --- the policy never answers differently --------------------------------------------------
    # Upstream of everything below. While this holds, every claim about a refusal is true without
    # testing anything, and both gates further down fire for reasons that are symptoms of it.
    if run.decision == "constant":
        return Ask(
            "the policy's decision",
            "Every request the draft named was refused by this policy, so the claim held without "
            "testing anything -- true the way 'nothing forbidden was allowed' is true when nothing "
            "was allowed at all.",
            "What has to have happened BEFORE the request you care about, for the policy to allow "
            "it?",
            "an approval, a verification, a prior read -- and roughly how long before")

    # --- a broken policy passes too ------------------------------------------------------------
    if run.rejected_at == "score":
        # NOT A QUESTION FOR A PERSON. A module that compiles and then dies evaluating has almost
        # always broken the tagging discipline -- `x = 1` against a `Num(1)` -- which is a fault in
        # the drafter's TLA+, and no restatement of a requirement in English can reach it. This
        # asked somebody to say their requirement again, after they had already answered it well,
        # for a fault their words had nothing to do with.
        if any("could not be evaluated" in c for c in run.complaints):
            return None
        if any("did not compile" in c for c in run.complaints):
            return restate(run, "The draft did not compile, so nothing was checked.")
        # ASKS FOR BOTH DIRECTIONS, and the second half is the one that matters. Every mutation
        # tried removes or narrows a permission -- a rule deleted, a permit typed as a forbid, a
        # condition dropped -- so a policy that refuses MORE still refuses everything a
        # refusal-only property said must be refused, and such a property survives all of them.
        #
        # THE OLD QUESTION CAUSED THAT. "Name one thing this policy must NEVER allow" is a request
        # for a refusal, a drafter answering it faithfully writes refusal-only claims, and this
        # gate then rejects them -- so the question sent the person round a loop it had built. It
        # cost three live sessions. The property that eventually passed differed from the ones that
        # did not by exactly one claim: a positive one.
        return Ask(
            "discrimination",
            "The claim holds -- but it also holds of every deliberately broken version of this "
            "policy set that was tried: rules deleted, permits turned into forbids, conditions "
            "dropped. So it is not constraining this policy set at all.\n\n"
            "Breaking a policy set mostly takes permissions AWAY, and a claim that something must be "
            "refused survives that. What catches it is a claim about something that must go "
            "THROUGH.",
            "Name two things: one this policy must NEVER allow, and one it MUST allow -- a request "
            "that has met every condition and has to succeed.",
            "a concrete action and values for each")

    # --- the claim cannot fail -----------------------------------------------------------------
    if run.rejected_at == "preflight":
        if any("cannot fail" in c for c in run.complaints):
            return Ask(
                "what it examines",
                "The claim can never fail: none of the cases it looked at can make its condition "
                "true, so it would pass without examining anything.",
                "Which exact values should this be checked at?",
                "the ports, amounts, roles or times where the rule actually bites")
        return restate(run, plainly(run.complaints))

    # --- a second model says it is about something else ----------------------------------------
    if run.rejected_at == "review":
        return Ask(
            "the round trip",
            "A second model was shown your requirement and a plain-English reading of the claim "
            "written to capture it -- never the formal claim -- and judged that they do not "
            f"match:\n\n{run.review_said.strip()}\n\nThe reading it was shown:\n\n"
            f"{run.explained.strip()}",
            "Is that reading what you meant? If not, say what it gets wrong. If it IS what you "
            "meant, say `keep`.",
            "`keep` overrules the reviewer -- that gate is a model's judgement, and yours outranks "
            "it")

    # --- the allowance ran out with nothing to show --------------------------------------------
    if run.exhausted:
        return restate(run, "Every drafting attempt was rejected before it could be checked.")

    return None


def plainly(complaints: list[str]) -> str:
    """A gate's complaint, said to somebody who did not write the module.

    THE GATES TALK TO THE DRAFTER, and they should: "the .cfg names INVARIANT OutsideIsRefused,
    which the module does not define. TLC stops with an error rather than checking anything" is
    exactly the right sentence for the thing that is going to try again. It is the wrong sentence
    for a person who was asked for a requirement in English and never saw a .cfg -- and passing it
    straight through was the first thing `tests/strands/hitl_loop.py` caught.

    SO NOTHING IS FORWARDED VERBATIM. Every branch below returns text written here, and the default
    says less rather than reaching for the complaint it could not classify -- an unrecognised
    complaint is precisely the one most likely to be full of TLA+.
    """
    said = " ".join(complaints).lower()
    if "does not define" in said:
        return ("The draft listed a claim it never actually wrote down, so there was nothing to "
                "check.")
    if "did not compile" in said or "could not be read" in said:
        return "The draft was not well-formed, so nothing was checked."
    if "did not contain both" in said:
        return "The draft came back incomplete."
    return "The draft could not be used as a property."


def restate(run: Run, why: str) -> Ask:
    """The fallback: a drafting failure the person cannot fix, but can make less likely.

    Asking somebody to repair a TLA+ module they did not write would be the wrong question, and
    saying nothing would be worse. What a person CAN do is say the requirement again in the
    policy's own nouns -- a question about their own requirement, with the vocabulary shown so the
    answer names things that exist.
    """
    vocab = vocabulary(run)
    return Ask("drafting", why,
               "Say the requirement again, as concretely as you can: which action, which values, "
               "and what the policy must do about them.",
               f"this policy knows about --\n{vocab}" if vocab else "")


# ------------------------------------------------------------------------------------------------
# The checkpoint: what this will forbid, before anything is checked
# ------------------------------------------------------------------------------------------------
def stage_confirm(run: Run, _: str, console: Console) -> str:
    """Show the person what the claim forbids, and ask whether that is what they meant.

    THE ONE STEP THAT RUNS EVEN WHEN EVERY GATE PASSED, and the only thing in the whole pipeline
    that can catch a property which is well-formed, discriminating, agreed to by a second model,
    and about the wrong rule. Every gate before it compares the property against the POLICY or
    against another model; this compares it against the person who asked for it.

    It is also the cheapest check here. `explain` is already in hand from `preflight`, it costs
    milliseconds, and it happens BEFORE the TLC runs rather than after -- so a misread requirement
    is caught before it is expensively confirmed. It is the one recommendation the survey in
    `reference/README.md` makes that needs no verification machinery at all.

    FAIL-OPEN WITH NO READING. `explain` producing nothing means there is nothing to put in front
    of a person, and stopping there would block on the absence of a question rather than on an
    answer.
    """
    if not run.explained.strip():
        return gate(True, "no plain-English reading was available to confirm")

    console.say()
    console.say("-" * 78)
    console.say("BEFORE ANYTHING IS CHECKED -- this is what the claim will forbid:")
    console.say()
    console.say(readable(run.explained))
    console.say("-" * 78)

    if console.confirm("Is that what you meant?"):
        run.confirmed = True
        return gate(True, "the person read what the claim forbids and confirmed it")

    said = console.ask("What does it get wrong?",
                       hint="in your own terms; the draft is rewritten from what you say")
    run.rejected_at = "confirm"
    run.complaints = ["the person did not confirm the reading of the claim: "
                      + (said or "no reason given")]
    if said.lower() not in STOP_WORDS:
        run.clarifications.append(("What does the reading of the claim get wrong?", said))
    return gate(False, run.complaints[0])


# ------------------------------------------------------------------------------------------------
# The loop
# ------------------------------------------------------------------------------------------------
@dataclass
class Session:
    """One person, one requirement, and however many attempts it took."""

    brief: str                   # WHAT THEY FIRST SAID, never edited. See `intent` below.
    policy: Path
    out: Path
    refinements: int = 4
    clarifications: list[tuple[str, str]] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    stopped: str = ""            # why the loop ended, when it did not end by passing

    @property
    def run(self) -> Run | None:
        return self.runs[-1] if self.runs else None

    @property
    def passed(self) -> bool:
        r = self.run
        return bool(r and not r.rejected_at and not r.unreachable and not r.crashed)

    def intent(self) -> str:
        """The brief, plus everything the person has said since.

        APPENDED, NEVER SUBSTITUTED, and the original stays verbatim at the top. Rewriting the
        brief out of the answers would lose the thing this mode is for: what was asked for is one
        text, what it turned out to mean is another, and a report showing only the second cannot be
        audited against the first. It is also what the reviewer compares against, so a summarised
        brief would quietly move the goalposts that gate is checking.
        """
        if not self.clarifications:
            return self.brief
        lines = [self.brief, "", "The person was then asked about this requirement, and said:"]
        for question, answer in self.clarifications:
            lines += ["", f"  Q: {question}", f"  A: {answer}"]
        return "\n".join(lines)


def refine(policy: Path, brief: str, console: Console, *, out: Path | None = None,
           refinements: int = 4, build_graph=None, **kw) -> Session:
    """Run the pipeline, ask about whatever stopped it, and run it again. Bounded, and it reports.

    EVERY EXIT WRITES A REPORT, including the ones where the person walked away. A session ending
    with nothing on disk is indistinguishable from one that was never started, and "we tried four
    times and here is what each attempt found" is a useful document even when the answer is that no
    property was kept.
    """
    # ITS OWN DIRECTORY, because `anchor/` already belongs to the sweep -- one directory per swept
    # requirement, checked in. A session writing `attempt-1/` and `session.md` beside those mixes
    # two kinds of artifact in one place, and makes the sweep's output look like it grew a stray run.
    session = Session(brief=brief, policy=policy,
                      out=out or policy.parent / "anchor" / "hitl", refinements=refinements)

    # A PREVIOUS SESSION'S ATTEMPTS ARE NOT THIS ONE'S. `session.md` is the index of what happened,
    # and a run that needed one attempt left `attempt-2/` sitting beside it from the run before --
    # a findings.md about a different draft, in this session's directory, named in nothing. Stale
    # and indistinguishable from current is the worst state for a verification artifact to be in.
    #
    # Only `attempt-<digits>` directories, only under the session's own output directory, and it
    # says what it removed.
    stale = sorted(p for p in session.out.glob("attempt-*") if p.is_dir()
                   and p.name.removeprefix("attempt-").isdigit())
    if stale:
        console.say(f"clearing {len(stale)} attempt directory/ies from a previous session: "
                    + ", ".join(p.name for p in stale))
        for p in stale:
            shutil.rmtree(p, ignore_errors=True)

    for attempt in range(1, max(1, refinements) + 1):
        said_so_far = len(session.clarifications)
        run = Run(policy=policy, intent=session.intent(),
                  out=session.out / f"attempt-{attempt}", **kw)
        run.clarifications = list(session.clarifications)
        if session.runs and session.runs[-1].complaints:
            # CARRIED, so a gate does not have to tell the drafter the same thing twice. Without
            # it every attempt starts from a clean brief plus the person's answer, and a draft
            # rejected for not compiling is free to make the identical mistake again.
            run.carried = ("Your previous attempt was rejected:\n"
                           + "\n".join(session.runs[-1].complaints))

        graph = (build_graph or pipeline.build)(run)
        result = graph(f"State and check the intention for {policy.name}.")
        pipeline.append_usage(run, result)
        # The confirm node appends to the run's copy; the session owns the accumulated list.
        session.clarifications = list(run.clarifications)
        session.runs.append(run)

        console.say()
        console.say(f"attempt {attempt}: {outcome(run)}"
                    + (f"  ({run.findings})" if run.findings else ""))

        if session.passed:
            return session

        ask = ask_about(run)
        if ask is None:
            if run.rejected_at == "confirm":
                # ASKED ALREADY, inside the run -- but only a clarification makes the next attempt
                # different. Somebody who says no at the checkpoint and then declines to say what
                # is wrong has left, and going round again would re-draft from an unchanged brief
                # and put the identical reading in front of them, once per remaining attempt.
                if len(session.clarifications) > said_so_far:
                    continue
                session.stopped = "the person ended the session"
                console.say("Stopping here. What was found so far is in the report.")
                return session
            # Said plainly rather than left as an outcome line. A model that cannot be reached and
            # a policy that will not parse both look like "it did not work", and neither is worth
            # another attempt.
            session.stopped = f"nothing a clarification can fix: {outcome(run)}"
            console.say()
            console.say(f"Stopping: {session.stopped}.")
            for line in run.unreachable + run.crashed + run.complaints:
                console.say(f"  {line}")
            return session

        console.say()
        console.say("-" * 78)
        console.say(ask.said)
        console.say("-" * 78)
        answer = console.ask(ask.question, hint=ask.hint)

        if answer.lower() in STOP_WORDS:
            session.stopped = "the person ended the session"
            console.say("Stopping here. What was found so far is in the report.")
            return session

        if ask.gate == "the round trip" and answer.lower().strip(" .!") == "keep":
            # THE PERSON OUTRANKS THE REVIEWER, and only the reviewer. Every other gate is a
            # criterion in code with an exact answer and there is nothing there to overrule; this
            # one is a model's judgement about a translation, and the person who wrote the
            # requirement is the better authority on whether it was captured. Recorded as an
            # override rather than applied quietly -- the report has to say a gate was overruled,
            # and by whom.
            session.clarifications.append(
                (ask.question, "The person read the plain-English reading and confirmed it says "
                               "what they meant, overruling the reviewing model."))
            continue

        session.clarifications.append((ask.question, answer))

    session.stopped = f"the allowance of {refinements} attempt(s) ran out"
    console.say()
    console.say(f"Stopping: {session.stopped}.")
    return session


def transcript(session: Session) -> str:
    """What the person contributed, and what each attempt made of it.

    A SEPARATE DOCUMENT FROM findings.md, which is about one attempt. This is about the session,
    and it answers the question an auditor asks first: a property that passed every gate on the
    fourth try, after the person was told three times what was wrong with the previous three, is a
    different artifact from one that passed on the first -- and that difference is visible in
    neither the module nor the verdicts.
    """
    lines = [f"# {session.policy.name}: a session", "",
             "**What was first asked for.**", "", f"> {session.brief}", ""]
    if session.clarifications:
        lines += ["**What the person was asked, and what they said.**", ""]
        for question, answer in session.clarifications:
            lines += [f"- *{question}*", f"  > {answer}", ""]
    elif session.passed:
        lines += ["The person was asked nothing: the first attempt passed every gate.", ""]
    elif session.stopped.startswith("the person"):
        # ASKED AND DECLINED, which is not the same as never asked. The first version of this file
        # said "the first attempt passed every gate" whenever nobody had answered; the second said
        # "asked nothing" for a session where a gate DID put a question to them and they chose to
        # stop. Three outcomes, three sentences -- an empty clarification list is the one thing all
        # three have in common and it distinguishes none of them.
        lines += ["The person was asked, and ended the session without answering.", ""]
    else:
        lines += ["The person was asked nothing, and the session did not pass: it stopped at "
                  "something no clarification could fix.", ""]

    lines += ["| attempt | outcome | rounds | tokens | findings |", "|---:|---|---:|---:|---|"]
    for i, run in enumerate(session.runs, 1):
        where = f"`{run.findings.parent.name}/{run.findings.name}`" if run.findings else "—"
        lines.append(f"| {i} | {outcome(run)} | {run.round} | "
                     f"{sum(c.total for c in run.calls):,} | {where} |")

    lines += ["", f"**{sum(sum(c.total for c in r.calls) for r in session.runs):,} tokens** over "
              f"{sum(len(r.calls) for r in session.runs)} model call(s) in "
              f"{len(session.runs)} attempt(s)."]
    if session.stopped:
        lines += ["", f"**The session did not end by passing:** {session.stopped}."]
    elif session.passed:
        lines += ["", "The last attempt passed every gate, and the person confirmed the "
                  "plain-English reading of the claim before anything was checked."]

    # THE CLAIM THIS SESSION IS ALLOWED TO MAKE, and it is not "verified by a human". A person
    # stated what they meant and agreed that a reading of the claim matched it; nobody read the
    # TLA+, and the gates that did are the same gates as in `auto`.
    #
    # AND ONLY IF THEY ACTUALLY DID. Being in `hitl` is not a confirmation: a session whose
    # allowance ran out asked four questions and got no property, and a footer that credits a
    # confirmation there is claiming the strongest thing in the document on the strength of the
    # mode it was run in. Written unconditionally at first, and it read as a confirmation on a
    # session where nobody confirmed anything.
    confirmed = any(r.confirmed for r in session.runs)
    lines += ["", "---", "",
              "*The property was drafted by a model and gated by Anchor. A person stated the "
              "requirement and confirmed a plain-English reading of the claim, which is better "
              "evidence than an unattended run and is still not a person having written the "
              "property.*" if confirmed else
              "*Nothing here was confirmed by the person: no draft reached the checkpoint where "
              "they are shown what it would forbid. The requirement above is theirs; every verdict "
              "is Anchor's, under the same gates as an unattended run.*", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------
# What each stage is doing, for somebody watching it happen. The two that matter are `draft` and
# `score`: between them they are almost the whole wait, and neither looks any different from a hung
# process while it is working.
DOING = {
    "describe": "reading the policy's vocabulary",
    "draft": "asking the model for a property module -- the long one",
    "preflight": "reading the draft",
    "score": "breaking the policy on purpose, one check per mutant -- the other long one",
    "review": "asking a second model whether it says what you asked for",
    "confirm": "over to you",
    "check": "running the checks",
    "answer": "writing it up",
    "report": "writing findings.md",
}


# How wide the overwrite has to be: the longest "  stage      note ..." line any of them produces,
# plus the `\r` that does not occupy a column. Derived rather than chosen, so adding a longer note
# cannot leave its tail on screen.
WIDEST = max(len(f"  {stage:<10} {note} ...") for stage, note in DOING.items()) + 1


def progress(console: Console):
    """Say what is happening, because otherwise nothing does until the first question.

    THE DEFECT THIS FIXES WAS FOUND BY RUNNING IT. `auto` reports each policy as it lands, for
    exactly this reason -- "is it stuck or working?" is what a long run should answer -- and the
    interactive mode, where somebody is actually sitting there, printed nothing at all between the
    command and the first prompt. On a six-field policy that is several minutes of model calls and
    TLC runs looking identical to a hang.
    """
    def announce(stage: str, seconds: float | None) -> None:
        if seconds is None:
            console.say(f"  {stage:<10} {DOING.get(stage, '')} ...", newline=False)
        else:
            # PADDED PAST THE LONGEST NOTE THERE IS, not past a guess. A fixed 60 was shorter than
            # `score`'s line and left "ong one ..." sitting after the elapsed time -- the tail of
            # the sentence it was supposed to paint over.
            console.say(f"\r  {stage:<10} {seconds:6.1f}s".ljust(WIDEST))
    return announce


def stated_intent(policy: Path, intents: Path | None, console: Console) -> str | None:
    """The requirement for `policy` out of an intents file, or None to go and ask for it.

    THE SAME FILE `auto` SWEEPS A DIRECTORY WITH, so a requirement written once is reachable from
    both modes rather than retyped into this one. Its headings are `## <policy>.dw` there; a file
    about a single policy SET uses one heading per requirement instead, and those cannot be matched
    by name -- so a lone entry is taken and several are shown rather than guessed between.

    FALLING THROUGH TO THE QUESTION IS THE POINT, and it is the whole difference from `auto`. A
    missing file, a file with no heading for this policy, a file whose headings are labels: none of
    those is an error here, because there is a person to ask. The one exception is an intents file
    named explicitly and not present, which is a typo rather than an absence.
    """
    path = intents or policy.parent / "intents.md"
    if not path.is_file():
        if intents is not None:
            print(f"no intents file at {path}", file=sys.stderr)
            raise SystemExit(2)
        return None

    stated = pipeline.read_intents(path)

    def named(what: str) -> str | None:
        return pipeline.intent_for(stated, what)

    found = named(policy.name) or (next(iter(stated.values())) if len(stated) == 1 else None)
    if found:
        # SHOWN, not used silently. The person did not type this one, and it is the sentence the
        # whole session is about -- including the confirm gate, which reads a claim back against it.
        console.say(f"{path.name} states: {found}")
        return found

    # NOTHING NAMES THIS POLICY AND THERE IS MORE THAN ONE CANDIDATE, which is the shape an intents
    # file takes when its headings are requirements against one policy SET rather than one file
    # each. `auto` runs all of them; a session is one requirement, so here it is a choice. Asking
    # which beats listing them and then asking a blank question the person would answer by retyping
    # a sentence the file already holds.
    if stated:
        console.say(f"{path.name} states no requirement for {policy.name}. It states {len(stated)}:")
        for heading in sorted(stated):
            console.say(f"  {heading}")
        said = console.ask("Which of those is this session about?",
                           hint="a name from that list, or the requirement in your own words")
        # A name gets its stated text; anything else IS the requirement -- including a stop word,
        # which main reads as "no requirement given" exactly as it would from the open question.
        return named(said) or said

    return None


def build_hitl(run: Run, console: Console, **kw):
    """`pipeline.build`, with the person's checkpoint between `review` and `check`."""
    return pipeline.build(run, confirm=lambda r, t: stage_confirm(r, t, console),
                          announce=progress(console), **kw)


def main() -> int:
    # ANCHOR_VERB is set by the launcher, so usage names `anchor hitl` rather than a file the
    # person never invoked. Unset when the script is run directly, and argparse then does what
    # it always did.
    p = argparse.ArgumentParser(prog=os.environ.get("ANCHOR_VERB") or None,
                                description=__doc__.splitlines()[0])
    p.add_argument("policy", type=Path, help="the .dw policy the requirement is about")
    # `--intent` is the pipeline's name for the same string and the name of the field it lands
    # in. `--brief` stays as an alias because it is what this file documented until now.
    p.add_argument("--intent", "--brief", dest="intent", default=None,
                   help="the requirement, in your own words. Read from --intents or asked for if "
                        "not given")
    p.add_argument("--intents", type=Path, default=None,
                   help="a markdown file of `## <policy>.dw` headings with the requirement under "
                        "each -- the file `auto` sweeps a directory with. Defaults to intents.md "
                        "beside the policy; no entry for it falls through to asking")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--event-schema", type=Path, default=None)
    p.add_argument("--mutants", type=int, default=8)
    p.add_argument("--max-fields", type=int, default=None)
    p.add_argument("--name", default="Intent", help="the property module's name")
    p.add_argument("--config", type=Path, default=None, metavar="APPSETTINGS.JSON",
                   help="the settings file holding the model configuration and API key. Defaults "
                        "to appsettings.json beside src/agent/ or at the repo root; in a container "
                        "this is how a mounted one is named")
    p.add_argument("--provider", default="auto", help="auto, bedrock or gemini")
    p.add_argument("--llm", default=None,
                   help="the LLM's model id. Defaults to the provider's Model setting "
                        "(Gemini:Model or Bedrock:Model), then the provider's own default")
    p.add_argument("--rounds", type=int, default=3,
                   help="drafting attempts WITHIN one pass, before the person is asked")
    p.add_argument("--refinements", type=int, default=4,
                   help="how many times the person may be asked before the session ends")
    p.add_argument("--turns", type=int, default=None)
    p.add_argument("--total-tokens", type=int, default=None)
    p.add_argument("--output-tokens", type=int, default=None)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--allow-flagged-input", action="store_true",
                   help="show the model inputs the scan flagged as high severity anyway, after "
                        "reading the findings. The session record says it was used")
    args = p.parse_args()

    # Before anything is read from them, and before the sweep globs children off `policy`.
    pipeline.absolute(args, "policy", "intents", "out", "event_schema")

    # BEFORE ANY MODEL IS SHOWN ANYTHING -- the same gate `auto` uses, so the two cannot disagree.
    blocked, scanned = pipeline.screen_inputs(args.policy, intents=args.intents,
                                              event_schema=args.event_schema, intent=args.intent,
                                              allow=args.allow_flagged_input)
    if blocked is not None:
        return blocked

    # BEFORE anything builds a model, and before the graph is built at all: every read of this
    # file happens inside policy_agent, lazily, so setting it here reaches all of them.
    if args.config is not None:
        policy_agent.use_appsettings(args.config)

    if not args.verbose:
        import logging                                                  # noqa: PLC0415
        logging.getLogger("google_genai.models").setLevel(logging.ERROR)

    console = Terminal()

    # A MODE THAT NEEDS A PERSON MUST REFUSE TO RUN WITHOUT ONE. Left alone this blocks on `input`
    # forever under a runner, or -- worse, on a pipe -- reads EOF as an answer and spends a model
    # call per attempt talking to nobody. `auto` is the mode for an unattended run, and it is one
    # word away.
    if not at_a_terminal():
        print("hitl needs a terminal: it asks questions and waits for answers. For an unattended "
              "run use `anchor auto` (src/agent/pipeline.py), which reports rather than asks.",
              file=sys.stderr)
        return 2

    brief = args.intent or stated_intent(args.policy, args.intents, console) or console.ask(
        f"What should {args.policy.name} guarantee?",
        hint="one sentence in your own words -- what you would tell a colleague the rule is")
    if brief.lower() in STOP_WORDS:
        print("no requirement given", file=sys.stderr)
        return 2

    # A requirement typed at the prompt reaches the drafter too, and pasted text is where a
    # payload would come from. From --intent or intents.md it was screened above already; saying
    # so twice costs nothing, and letting a pasted one through unscreened would.
    if not args.intent:
        from checker import scan as screen                              # noqa: PLC0415
        typed = screen.scan([], {"the requirement": brief})
        if screen.gate(typed, allow=args.allow_flagged_input, who="the model") is not None:
            return 2
        if typed.high or typed.medium:
            # Joined to what the files said, not in place of it.
            scanned = {"input_scan": "; ".join(filter(None, [scanned.get("input_scan"),
                                                             f"the typed requirement: {typed.summary()}"])),
                       "input_scan_overridden": scanned.get("input_scan_overridden", False)
                                                or bool(typed.high)}

    session = refine(
        args.policy, brief, console,
        out=args.out, refinements=args.refinements,
        build_graph=lambda r: build_hitl(r, console, provider=args.provider, model=args.llm),
        event_schema=args.event_schema, module_name=args.name, mutants=args.mutants,
        rounds=args.rounds, max_fields=args.max_fields,
        limits={k: v for k, v in (("turns", args.turns),
                                  ("total_tokens", args.total_tokens),
                                  ("output_tokens", args.output_tokens)) if v},
        **scanned)

    session.out.mkdir(parents=True, exist_ok=True)
    where = session.out / "session.md"
    where.write_text(transcript(session), encoding="utf-8")

    console.say()
    console.say(f"{sum(sum(c.total for c in r.calls) for r in session.runs):,} tokens over "
                f"{len(session.runs)} attempt(s)")
    print(where)
    return 0 if session.passed else 1


if __name__ == "__main__":
    sys.exit(main())
