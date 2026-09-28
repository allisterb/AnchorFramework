"""Finding the TLA+ tools jar, and running TLC with the flags that stop it eating itself.

The jar version lives in exactly one place -- `tlatools_version` in `build.sh`, next to the sha256
checked on every run. Harnesses used to spell `tla2tools-1.7.4.jar` themselves, so bumping that pin
would have left six of them looking for a jar that no longer existed: a `FileNotFoundError` naming
a path, locally and in CI at once, with nothing pointing at the version bump that caused it.
Resolved by glob instead, so whatever the build installed is what runs.

Resolved WHEN TLC IS RUN, not at import: `dw_to_tla.py` translates without ever starting a JVM
(`--check` is a text comparison), so it has to keep working in a tree with no jar yet.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path

from .policy_module import DECISION_KIND

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "lib"


@lru_cache(maxsize=1)
def find_jar() -> Path:
    """The tla2tools jar the build installed.

    Raises rather than returning a path that does not exist: the alternative is java reporting
    `Could not find or load main class tlc2.TLC`, which describes neither the problem nor the fix.
    """
    jars = sorted(LIB.glob("tla2tools-*.jar"))
    if not jars:
        raise SystemExit(
            f"no tla2tools jar in {LIB.relative_to(REPO)}/\n"
            "It is downloaded and sha256-checked by the build, not committed. Run:\n"
            "    ./build.sh        (or ./build.ps1 on Windows)")

    # Newest last, so a lib/ holding two after a bump uses the later one. The build installs only
    # ever one, so this is a tie-break that should not come up.
    return jars[-1]


def run_tlc(module: str, cwd: Path, scratch: Path | None = None,
            extra: list[str] | None = None) -> tuple[bool, str]:
    """Run TLC on `module` in `cwd`, returning (it passed, everything it printed).

    `extra` goes in front of `-config`, which is where TLC wants mode flags such as
    `-simulate num=N`. Passed through rather than enumerated here: this module knows how to start a
    JVM safely, not what any particular check is asking.

    THE `-Djava.io.tmpdir` IS NOT OPTIONAL, and it is why this function exists. TLC unpacks the
    standard modules into java's temp directory; runs sharing one leave a half-written
    `Naturals.tla` behind, and SANY reports that as a NullPointerException plus a "Module-Table
    lookup failure" naming whichever *unrelated* spec lost the race. About one run in four, and the
    error points at a perfectly good file.

    `TLCProcess.cs` carried the fix for the C# runner while all five Python harnesses spawned TLC
    without it, which is what a copy-pasted command line costs: xunit runs tests in parallel, so
    two harnesses racing was the ordinary case rather than bad luck. One shared entry point makes
    that impossible to get wrong again.
    """
    with (tempfile.TemporaryDirectory(prefix="anchor-tlc-") if scratch is None
          else nullcontext(str(scratch))) as tmp:
        cmd = ["java", *JAVA_UTF8, *java_options(), f"-Djava.io.tmpdir={tmp}",
               "-cp", str(find_jar()), "tlc2.TLC", "-cleanup",
               "-metadir", str(Path(tmp) / "states"),
               *(extra or []),
               "-config", f"{module}.cfg", f"{module}.tla"]
        if os.environ.get("ANCHOR_PROGRESS"):
            return relay_progress(cmd, cwd)
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        return proc.returncode == 0, proc.stdout + proc.stderr

def relay_progress(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    """`run_tlc` for a caller that asked for progress: TLC's own `Progress(...)` lines are echoed to
    stderr as they arrive, and everything is still returned exactly as the quiet path returns it.

    TLC prints one about once a minute on a long search, which is the only sign a ten-minute run is
    alive. stderr is read on a thread so that neither pipe can fill while the other is being read.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    out: list[str] = []
    for line in proc.stdout:
        out.append(line)
        if line.startswith("Progress"):
            print(f"        {line.rstrip()}", file=sys.stderr, flush=True)
    proc.wait()
    reader.join()
    return proc.returncode == 0, "".join(out) + "".join(errors)



def run_sany(module: str, cwd: Path) -> tuple[bool, str]:
    """Parse and semantically check `module` with SANY, without running TLC.

    A second of work rather than minutes, which is the whole point: a property module is TLA+
    somebody (or something) has just written, and the commonest thing wrong with it is that it does
    not compile. Finding that out from a model-checking run means paying for the run first, and
    reading the answer out of TLC's preamble.

    **SANY REPORTS ITS ERRORS AND THEN EXITS 0.** An unknown operator prints `*** Errors: 1` with a
    line and column, and the process still returns success -- so branching on the exit code alone
    declares a module sound because it failed to compile quietly. The output is what carries the
    verdict, and this reads it. Same rule as everywhere else here: never let a failure read as an
    absence of data.
    """
    with tempfile.TemporaryDirectory(prefix="anchor-sany-") as tmp:
        proc = subprocess.run(
            ["java", *JAVA_UTF8, *java_options(), f"-Djava.io.tmpdir={tmp}",
             "-cp", str(find_jar()), "tla2sany.SANY", f"{module}.tla"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    out = proc.stdout + proc.stderr
    broken = ("*** Errors" in out or "*** Abort" in out or "Could not parse" in out
              or proc.returncode != 0)
    return not broken, out.strip()


# The value is bracketed so it can be lifted out of everything else TLC prints, which for a
# multi-line record is several screens of preamble away from the answer. Taken from will62794's
# `tlaplus_repl`, which does the same; see reference/README.md.
EVAL_START = "ANCHOR_EVAL_START"
EVAL_END = "ANCHOR_EVAL_END"

EVAL_MODULE = """---------------------------- MODULE {name} ----------------------------
EXTENDS Integers, Sequences, FiniteSets, {extends}

\\* INSTANCE, NOT EXTENDS, and this is not a style choice. Extending TLC here made evaluation of
\\* the policy semantics FAIL on any policy whose rules join across value kinds -- TLC reported
\\* "Attempted to check equality of string ... with non-string: TRUE" and, on a second run, "TLC
\\* was unable to fingerprint". The same expression, in the same module, checked as an INVARIANT
\\* rather than an ASSUME, evaluates correctly; so does an ASSUME once TLC arrives by INSTANCE.
\\* Reproduced on examples/aws2/agent-policy.dw with both a hand-written and a drafted module.
\\*
\\* THE TRIGGER NEEDS BOTH HALVES, which is why one rule was not enough to reproduce it: a join
\\* comparing across value kinds (a string account beside a boolean flag) AND an aggregate binding
\\* over the trace's scalars. Either alone evaluates correctly under EXTENDS.
\\*
\\* WHY extending it does that is NOT established -- the tagged value model and TLC's own
\\* normalisation are the obvious suspects and neither was confirmed. What is established is the
\\* reproduction and the fix, and `tests/policies/eval_join.dw` holds the line.
T == INSTANCE TLC

ASSUME /\\ T!PrintT("{start}")
       /\\ T!PrintT({expr})
       /\\ T!PrintT("{end}")
============================================================================
"""


def run_eval(expr: str, extends: str, cwd: Path, spec: str | None = "Spec") -> tuple[bool, str]:
    """Evaluate `expr` in the context of module `extends`, and return what it is.

    THIS IS NOT MODEL CHECKING and it is not meant to be. `ASSUME PrintT(e)` makes TLC evaluate `e`
    once, during initialisation, and print the value -- so a question like "what is `Session(960)`"
    or "what does this policy decide for it" is answered in a couple of seconds instead of by
    writing an invariant and running a check to find out.

    THE CONFIG HAS TO NAME A SPEC when the extended module declares variables. TLC validates the
    config BEFORE it evaluates assumptions, so an empty one fails with "did not specify the initial
    state predicate" and the expression is never reached -- the assumption prints nothing and the
    absence looks like an empty answer. A property module always declares a variable, so `Spec` is
    the default here rather than the exception.

    The EXIT CODE IS IGNORED, deliberately. TLC may go on to complain about the model after the
    value has been printed -- there is nothing to check and we did not ask it to -- and the value is
    already in hand. What decides success is whether the markers came back.
    """
    name = "AnchorEval"
    module = EVAL_MODULE.format(name=name, extends=extends, expr=expr,
                                start=EVAL_START, end=EVAL_END)
    (cwd / f"{name}.tla").write_text(module, encoding="utf-8")
    (cwd / f"{name}.cfg").write_text(f"SPECIFICATION {spec}\n" if spec else "", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="anchor-eval-") as tmp:
        proc = subprocess.run(
            ["java", *JAVA_UTF8, *java_options(), f"-Djava.io.tmpdir={tmp}",
             "-cp", str(find_jar()), "tlc2.TLC", "-deadlock", "-cleanup",
             "-metadir", str(Path(tmp) / "states"),
             "-config", f"{name}.cfg", f"{name}.tla"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    out = proc.stdout + proc.stderr
    lines = out.splitlines()
    try:
        first = next(i for i, l in enumerate(lines) if EVAL_START in l)
        last = next(i for i, l in enumerate(lines) if EVAL_END in l and i > first)
    except StopIteration:
        # No markers: the expression did not evaluate. The reason is in TLC's output and is
        # returned whole -- an unreadable answer beats a confident empty one.
        return False, out.strip()

    return True, "\n".join(lines[first + 1:last]).strip()


# UTF-8 in and out, whatever the platform: the .tla files are UTF-8, and so is how we read
# what TLC prints. Java's default charset is the platform's -- cp1252 on Windows -- so without
# these a non-ASCII string in a module was read as cp1252 and printed back as mojibake, while
# Linux, and so CI and the container, already said the same thing correctly. `file.encoding`
# governs both directions on Java 11-17; 18 made UTF-8 the default for files but left stdout
# on the platform encoding until `stdout.encoding` and `stderr.encoding` arrived in 19. A JVM
# that does not know a property simply ignores it, so all three are safe everywhere.
JAVA_UTF8 = ["-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8"]

# The JVM flags to start TLC with, and there is deliberately no default.
JAVA_OPTIONS = "ANCHOR_TLC_JAVA_OPTS"


def java_options() -> list[str]:
    """Extra JVM flags for TLC, from `ANCHOR_TLC_JAVA_OPTS`. Empty unless somebody sets it.

    THE ONE WORTH KNOWING ABOUT IS `-XX:TieredStopAtLevel=1`, which stops the JVM's C2 optimising
    compiler from running. It is a real trade and the crossover was measured rather than guessed:

        1 run, 40 states           1.90s -> 1.59s     16% faster
        8 concurrent, 40 states    8.92s -> 4.68s     1.9x faster
        1 run, 960k states         3.72s -> 4.00s     8% SLOWER
        1 run, 6.7M states        12.17s -> 18.67s    53% SLOWER

    Which is exactly what it should do. A short run never runs long enough for C2's compilation to
    pay for itself, and eight of them at once are eight JVMs each spending cores on background
    compilation they will not benefit from; a long search is the opposite case, and there the
    optimised code is most of the throughput.

    So there is no setting that is right for both, and picking one globally would mean picking it
    for the runs that care least. It is left unset for anything a person runs -- their policy might
    be the big one -- and set by the TEST harness, where every model is bounded small by
    construction and six of them compete for the machine. See tests/Anchor.Tests.Verifier.
    """
    return shlex.split(os.environ.get(JAVA_OPTIONS, ""))


# ---------------------------------------------------------------------------- reading a trace back
#
# TLC prints a counterexample as a sequence of states in TLA+ value syntax. `witness()` in the
# checker reduces one to a single line for a person to read; this reads the whole thing back into
# Python, for the two readers a sentence does not serve:
#
#   a person who knows TLA+   and wants the actual states, not a paraphrase of them
#   an AGENT                  which has to act on the trace -- and cannot act on English
#
# The second is the one that makes this worth a parser rather than a regex. A repair loop reads
# the witness, changes the policy, and re-checks; that loop needs the input values that reached
# the bad decision, and "ApproveSale -> SellShares" does not carry them.

# TLA+ values, as TLC prints them. A small grammar and all of it is here:
#
#   record    [ name |-> value, ... ]        -- also how Anchor tags scalars
#   sequence  << value, ... >>               -- and << >> for empty
#   set       { value, ... }
#   string    "..."          number  123     boolean  TRUE / FALSE
#
# Deliberately NOT a general TLA+ parser. It reads what TLC emits for THIS spec's state, and
# anything else raises rather than guessing -- a trace that silently parsed wrong would be worse
# than no trace at all, because it would be acted on.
class TLAParseError(ValueError):
    """TLC printed something this reader does not model. Never swallowed: see the note above."""


def _skip(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def parse_tla_value(s: str, i: int = 0):
    """One TLA+ value from `s` at `i`. Returns (value, index just past it)."""
    i = _skip(s, i)
    if i >= len(s):
        raise TLAParseError("ran out of input")

    if s.startswith("<<", i):                                     # sequence
        i = _skip(s, i + 2)
        out = []
        if s.startswith(">>", i):
            return out, i + 2
        while True:
            v, i = parse_tla_value(s, i)
            out.append(v)
            i = _skip(s, i)
            if s.startswith(",", i):
                i = _skip(s, i + 1)
                continue
            if s.startswith(">>", i):
                return out, i + 2
            raise TLAParseError(f"expected , or >> at {i}: {s[i:i + 30]!r}")

    if s[i] == "[":                                               # record
        i = _skip(s, i + 1)
        rec = {}
        if s.startswith("]", i):
            return rec, i + 1
        while True:
            j = i
            while j < len(s) and (s[j].isalnum() or s[j] in "_"):
                j += 1
            if j == i:
                raise TLAParseError(f"expected a field name at {i}: {s[i:i + 30]!r}")
            name = s[i:j]
            j = _skip(s, j)
            if not s.startswith("|->", j):
                raise TLAParseError(f"expected |-> after {name!r} at {j}")
            v, i = parse_tla_value(s, j + 3)
            rec[name] = v
            i = _skip(s, i)
            if s.startswith(",", i):
                i = _skip(s, i + 1)
                continue
            if s.startswith("]", i):
                return rec, i + 1
            raise TLAParseError(f"expected , or ] at {i}: {s[i:i + 30]!r}")

    if s[i] == "{":                                               # set
        i = _skip(s, i + 1)
        out = []
        if s.startswith("}", i):
            return out, i + 1
        while True:
            v, i = parse_tla_value(s, i)
            out.append(v)
            i = _skip(s, i)
            if s.startswith(",", i):
                i = _skip(s, i + 1)
                continue
            if s.startswith("}", i):
                return out, i + 1
            raise TLAParseError(f"expected , or }} at {i}: {s[i:i + 30]!r}")

    if s[i] == '"':                                               # string
        j = i + 1
        buf = []
        while j < len(s):
            if s[j] == "\\" and j + 1 < len(s):
                buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(s[j + 1], s[j + 1]))
                j += 2
                continue
            if s[j] == '"':
                return "".join(buf), j + 1
            buf.append(s[j])
            j += 1
        raise TLAParseError("unterminated string")

    if s.startswith("TRUE", i):
        return True, i + 4
    if s.startswith("FALSE", i):
        return False, i + 5

    j = i + 1 if s[i] == "-" else i                                # number
    while j < len(s) and s[j].isdigit():
        j += 1
    if j > i and s[i:j] not in ("-", ""):
        return int(s[i:j]), j

    raise TLAParseError(f"unrecognised value at {i}: {s[i:i + 30]!r}")


# The generated module tags every scalar with its kind so TLC refuses a cross-kind comparison --
# `[k |-> "n", v |-> 1]` rather than `1`. That tagging is for the model checker's benefit and is
# noise to every reader here, so it is undone on the way out. The kind is not discarded silently:
# an address stays a list of four octets, which is visibly not a number.
_TAGGED = {"k", "v"}


def untag(value):
    """Strip Anchor's scalar tags from a parsed value, recursively."""
    if isinstance(value, dict):
        if set(value) == _TAGGED and isinstance(value.get("k"), str):
            return untag(value["v"])
        return {k: untag(v) for k, v in value.items()}
    if isinstance(value, list):
        return [untag(v) for v in value]
    return value


def trace_states(out: str) -> list[dict]:
    """Every state of TLC's counterexample, as dicts of variable name to value.

    Returns [] when the output carries no counterexample -- which is not an error: a run that
    completed without violating its invariant has no trace to show, and that is the answer.
    """
    states = []
    for block in re.split(r"^[ \t]*State \d+: ", out, flags=re.MULTILINE)[1:]:
        # A state block runs to the first blank line; what follows is the next state or TLC's
        # summary. Conjuncts are `/\ name = value`, one per (possibly wrapped) line.
        body = re.split(r"\n[ \t]*\n", block, maxsplit=1)[0]
        state = {}
        for chunk in re.split(r"^[ \t]*/\\ ", body, flags=re.MULTILINE)[1:]:
            name, _, rest = chunk.partition("=")
            try:
                value, _ = parse_tla_value(rest)
            except TLAParseError:
                # One unreadable variable must not cost the whole trace. Recorded as raw text so
                # it is visibly unparsed rather than missing.
                value = {"unparsed": rest.strip()}
            state[name.strip()] = untag(value)
        if state:
            states.append(state)
    return states


def witness_events(out: str) -> list[dict]:
    """The counterexample's session: the events of the final state's `trace`, in order.

    This is the sequence that reached the decision being reported -- the answer to "show me what
    actually happened", for a reader who wants more than the one-line summary.
    """
    states = trace_states(out)
    if not states:
        return []
    events = states[-1].get("trace") or []
    if not isinstance(events, list):
        return []

    # TLC prints an EMPTY FUNCTION as `<< >>`, which is indistinguishable from an empty sequence
    # at this level and parses as []. `output` and `pins` are always functions in this spec, so an
    # empty one is normalised to {} -- otherwise a consumer sees a list on the events that have no
    # output and an object on the ones that do, and has to handle both for no reason.
    for event in events:
        if isinstance(event, dict):
            for field in ("output", "input", "pins"):
                if event.get(field) == []:
                    event[field] = {}
    return events


# ---------------------------------------------------------------------------- telling the story
#
# The one-line summary -- `ApproveSale -> SellShares` -- names the actions and drops everything
# else: which values were passed, which attempts were refused, and which decision the verdict is
# actually about. For someone who will never open a `.tla` file that is most of the answer missing.
#
# These render the same events as sentences. Presentation only: nothing here decides anything, and
# a narrative that disagreed with the verdict would be a bug in the rendering rather than in the
# check.


def render_value(v) -> str:
    """One field value, as a person would write it.

    An ADDRESS is four octets rather than a 32-bit number -- TLC works in Java ints and stops at
    2147483647, so 208.4.4.0 cannot be held as one. It arrives here as a list of four and is
    printed dotted, because `[208, 4, 4, 0]` is not how anybody reads an IP address.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        if len(v) == 4 and all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            return ".".join(str(x) for x in v)
        return "[" + ", ".join(render_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {render_value(x)}" for k, x in v.items()) + "}"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


def render_fields(fields) -> str:
    """`stock = 1, amount = 2`, or empty when the policy reads nothing."""
    if not isinstance(fields, dict) or not fields:
        return ""
    return ", ".join(f"{k} = {render_value(v)}" for k, v in sorted(fields.items()))


def attempts_of(events: list[dict]) -> list[dict]:
    """The events paired into ATTEMPTS: one decision, and the outcome recorded for it.

    The model appends two events per attempt -- the `request` the decision is made on, then the
    outcome. AgentCore's convention is what makes the outcome readable: a permitted action that
    completed is recorded as `response`, a DENIED one as `error`, and the request is recorded
    either way. So the outcome kind is the verdict, and no separate decision field is needed.
    """
    out = []
    for i, e in enumerate(events):
        if not isinstance(e, dict) or e.get("kind") != DECISION_KIND:
            continue
        outcome = events[i + 1] if i + 1 < len(events) else None
        if not isinstance(outcome, dict) or outcome.get("kind") == DECISION_KIND:
            outcome = None
        out.append({
            "action": e.get("action", "?"),
            "input": e.get("input") or {},
            # None when the trace ends before the outcome -- said as "no outcome recorded"
            # rather than guessed at, because guessing "allowed" here would invent a permission.
            "allowed": None if outcome is None else outcome.get("kind") != "error",
            "output": (outcome or {}).get("output") or {},
            "who": e.get("principal"),
        })
    return out


def narrate(events: list[dict], final_note: str = "") -> list[str]:
    """The witness session as numbered lines, one per attempt.

    `final_note` is appended to the LAST attempt, which is the one the verdict is about: every
    attempt before it is setup that made the last one reachable. Marking it is the difference
    between showing a trace and explaining a decision.
    """
    attempts = attempts_of(events)
    if not attempts:
        return []

    lines = []
    width = max(len(a["action"]) for a in attempts)
    for n, a in enumerate(attempts, 1):
        fields = render_fields(a["input"])
        call = f"{a['action']:<{width}}({fields})" if fields else f"{a['action']:<{width}}()"
        verdict = {True: "allowed", False: "denied", None: "no outcome recorded"}[a["allowed"]]

        # Outputs only when the action completed AND produced some -- a denied attempt records
        # no results, so printing an empty set beside it would imply one was returned.
        out = render_fields(a["output"])
        tail = f"  ({out})" if out and a["allowed"] else ""

        note = f"   <- {final_note}" if final_note and n == len(attempts) else ""
        lines.append(f"{n}. {call}  {verdict}{tail}{note}")
    return lines
