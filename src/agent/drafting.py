"""The tools the DRAFTER gets, and the reason it does not get the others.

IT WAS WRITING TLA+ BLIND. The drafter was a bare `Agent` with a system prompt: one prompt in, a
module out, and it learned what was wrong with it a whole graph round-trip later, from feedback
assembled by `stage_draft`. Every mechanical mistake therefore cost a fresh model call on a
conversation that had grown by the previous attempt -- and three live sessions in a row died on one
typing rule that a two-line probe would have settled in seconds.

    check_module      does it compile, and does it evaluate against this policy
    what_it_forbids   the plain-English reading, and how many states each claim applies to
    evaluate          what is the value of this expression, in this module, under this policy

WHAT IS DELIBERATELY MISSING IS THE POINT OF THE FILE. There is no mutation scoring here and there
never should be. `score` asks whether the property notices the policy breaking, and a model that
can run it will tune the property until it catches a mutant -- which is optimising against the gate
rather than stating the requirement, a documented failure mode in agentic verification.
TLA-Prover (Spencer, Bisharat et al., arXiv:2606.06133) names it for TLA+: a model optimised on TLC
passing alone would learn invariants that are always true. It blocks that with a mutation test the
model is graded by but does not control, which is the separation kept here. The reviewing model
is absent for the same reason: it judges the property
against the REQUIREMENT, and a drafter that can consult it can negotiate with it.

So the line is: **the drafter may check its own mechanics, and may not see the gates that judge
it.** That is the same split `stage_draft` already enforces in its retry loop -- SANY, preflight
and one property check inside the node, `score` outside it and one shot -- so nothing new is
checked before scoring. What changes is who drives the loop, and how quickly the answer arrives.

LOCAL FUNCTIONS, NOT MCP. `Anchor.MCPServer` exposes most of this over stdio and `policy_agent.py`
speaks to it, which is right for an agent a third party drives. Here it would add a C# process the
pipeline does not otherwise need and would break the hermetic harness, which runs every scenario
with scripted models and no server at all. These call the same Python the gates call.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from strands import tool                                              # noqa: E402

from agent import author, invoke, repair                              # noqa: E402

# The names a caller can assert on. Kept here rather than derived, so a test can say "these and no
# others" and mean it -- the thing that must never drift is the ABSENCE of the gates.
TOOL_NAMES = ("check_module", "what_it_forbids", "evaluate")


def tools(run) -> list:
    """The three, closed over the run so they know which policy they are about.

    A `Run` carries the policy, the event schema and the field bound, and none of those should be
    arguments the model supplies: a drafter that can choose its own `--max-fields` can widen the
    check until something passes, and one that can choose the policy is not drafting against the
    policy it was asked about.
    """

    def scratch(module: str, config: str) -> tuple[Path, Path]:
        """The pair on disk, under a directory of this run's own. Overwritten every call.

        NOT the module `score` will read. That one is written by `stage_score` from the draft the
        node finally returns, and keeping these apart is what stops a tool call from deciding what
        gets checked -- the model's last word is the returned text, not the last file it wrote.
        """
        work = run.out / "drafting"
        work.mkdir(parents=True, exist_ok=True)
        tla = work / f"{run.module_name}.tla"
        tla.write_text(module, encoding="utf-8")
        tla.with_suffix(".cfg").write_text(config, encoding="utf-8")
        return tla, tla.with_suffix(".cfg")

    @tool
    def check_module(module: str, config: str) -> str:
        """Check a property module against the policy: does it compile, and does it evaluate?

        Call this on every draft BEFORE returning it. It runs the same checks the pipeline runs, so
        an answer of "nothing wrong" here is the answer you will get there.

        Args:
            module: the complete .tla file text.
            config: the complete .cfg file text, naming every invariant.
        """
        tla, _ = scratch(module, config)

        ok, out = author.compiles(run.policy, tla, event_schema=run.event_schema,
                                  max_fields=run.max_fields)
        if not ok:
            return f"DOES NOT COMPILE. SANY says:\n\n{briefly(out)[:1500]}"

        # STATIC BEFORE EXPENSIVE, the same order the pipeline uses.
        try:
            said = author.preflight(module, config, run.module_name, run.vocab)
        except Exception as e:                              # noqa: BLE001 - answered, not raised
            return f"Compiles, but the module could not be read: {e}"
        if said:
            return "Compiles, but:\n\n" + "\n".join(f"- {s}" for s in said)

        once = repair.check_property(run.policy, tla, event_schema=run.event_schema,
                                     max_fields=run.max_fields)
        if once.get("_failed"):
            return ("COMPILED BUT DID NOT EVALUATE:\n\n"
                    + briefly(str(once.get("_why")))[:1500] + "\n\n"
                    + (author.diagnose(str(once.get("_why"))) or TAGGING_HINT))

        held = "holds on this policy" if once.get("held") else "does NOT hold on this policy"
        # BOTH ARE FINE AND IT SAYS SO. A property that fails on the policy as written has already
        # shown it can tell one policy from another; a drafter told only "it does not hold" will
        # weaken the claim until it does, which is the failure this whole pipeline is built around.
        answer = (f"Compiles, evaluates, and {held}. Either answer is acceptable -- a property that "
                  f"fails has already shown it discriminates. Do NOT weaken the claim to make it "
                  f"hold.")
        # ADVICE, SAID WHILE IT IS STILL CHEAP. A module of refusal claims alone is the commonest
        # shape mutation scoring rejects, minutes later; here it is milliseconds, and the drafter
        # decides whether the requirement really is a pure prohibition.
        warning = author.refusal_only(module, config, run.module_name)
        return answer + (f"\n\n{warning}" if warning else "")

    @tool
    def what_it_forbids(module: str, config: str) -> str:
        """Read back, in plain English, what each claim forbids and how many states it applies to.

        Use this to check that the claim you wrote is the claim you meant, and that it is not
        true of every state before the policy is consulted.

        Args:
            module: the complete .tla file text.
            config: the complete .cfg file text.
        """
        from checker.explain import Module, explain, render            # noqa: PLC0415

        try:
            return without_the_state_list(
                render(explain(Module(module, config, run.module_name))))
        except Exception as e:                              # noqa: BLE001 - answered, not raised
            return f"The module could not be read: {e}"

    @tool
    def evaluate(expression: str, module: str, config: str) -> str:
        """Evaluate one TLA+ expression in the context of this module and policy.

        For settling a question about a value rather than about a whole module -- what a tagged
        value looks like, whether two of them are comparable, what a session decides.

        Args:
            expression: the TLA+ expression, e.g. `Num(1) = Num(1)` or `<<Grants(r1), Grants(r2)>>`.
            module: the complete .tla file text, whose definitions are in scope.
            config: the complete .cfg file text.
        """
        tla, _ = scratch(module, config)
        args = [str(run.policy), "--property", str(tla), "--eval", expression]
        if run.event_schema is not None:
            args += ["--event-schema", str(run.event_schema)]
        if run.max_fields is not None:
            args += ["--max-fields", str(run.max_fields)]

        try:
            proc = invoke.checker(args, timeout=300)
        except subprocess.TimeoutExpired:
            return "The expression did not finish within 300s."
        out = briefly((proc.stdout + proc.stderr).strip())
        return clipped(out, value=proc.returncode == 0) if out else "The checker said nothing."

    # THE ORDER IS TOOL_NAMES, so a caller asserting "these and no others" is comparing against
    # what is actually handed to the agent rather than against a list that agrees with it today.
    return [check_module, what_it_forbids, evaluate]


def briefly(out: str) -> str:
    """The checker's answer without the preamble it prints for a person.

    EVERY TOOL RESULT IS RE-SENT ON EVERY TURN of the agent loop, so what a tool returns is not
    paid for once -- it is paid for once per turn that follows it, and a drafter that calls three
    tools is carrying all three answers for the rest of the round. Measured on a live run: both
    attempts' first round was CUT OFF by the token cap mid-loop.

    The checker opens with a five-line note about event-schema readings, addressed to whoever ran
    it. It is the right thing to print at a terminal and pure weight here: the drafter does not
    choose the reading, `Run` does.
    """
    lines = out.splitlines()
    start = next((i for i, line in enumerate(lines) if ".dw against " in line), None)
    return "\n".join(lines[start + 1:] if start is not None else lines).strip()


EVAL_CHARS = 1500


def clipped(out: str, value: bool, limit: int = EVAL_CHARS) -> str:
    """`evaluate`'s answer cut to `limit` characters, SAYING SO.

    IT USED TO KEEP THE LAST 1500, SILENTLY. Right for a failure, whose reason TLC prints last;
    wrong for a value, which then arrived as the tail of a structure with no head and nothing to
    say it was cut. On the 2026-10-04 aws2 sweep one drafter asked for `Policies` three times
    running. So a value keeps its start, a failure its end, and either says how much is missing.
    """
    if len(out) <= limit:
        return out
    if not value:
        return (f"[TRUNCATED: the last {limit} of {len(out)} characters; TLC's reason is at the "
                f"end.]\n\n{out[-limit:]}")
    # The checker cuts a long value at a line count of its own, and says so on its last line --
    # which the head kept below would drop.
    more = re.search(r"^\.\.\. (\d+) more line\(s\) of the value not shown", out, re.M)
    rest = f", and {more[1]} more line(s) the checker did not print" if more else ""
    return (f"{out[:limit]}\n\n[TRUNCATED: the first {limit} of {len(out)} characters{rest}. "
            f"Evaluate a smaller part -- one element or one field -- to see the rest.]")


def without_the_state_list(reading: str) -> str:
    """`explain`'s rendering, minus the enumeration of every state it ranges over.

    The header lists the whole state space -- 3129 characters for a 64-state module, most of it
    that list. A person reading findings.md wants it; a drafter deciding whether its claim says the
    right thing wants the COUNT and the per-claim `applies to N of M`, both of which survive here.
    """
    out, dropping = [], False
    for line in reading.splitlines():
        if "claims will be checked, over" in line or "claim will be checked, over" in line:
            out.append(line)
            dropping = True                 # the enumeration follows, until the blank line
        elif dropping:
            if not line.strip():
                dropping = False
                out.append(line)
        else:
            out.append(line)
    return "\n".join(out)


TAGGING_HINT = (
    "Three rules, and the first and last are opposites. INSIDE an event's field record a value "
    "must be TAGGED -- `[amount |-> Num(60000)]`. COMPARING one: `=` and `#` take two tagged values "
    "(`s = Str(\"a1\")`), but `<`, `<=`, `>`, `>=` and arithmetic need the number inside, `.v` -- "
    "`x.v <= 22`; both `x <= 22` and `x <= Num(22)` die with `The first argument of <= should be "
    "an integer`. But a VARIABLE must range over PLAIN values and be "
    "tagged where it is USED: `verified \\in {TRUE, FALSE}` with `[verified |-> Bool(verified)]`, "
    "never `verified \\in {Bool(TRUE), Bool(FALSE)}`. Tagged values in an `Init` domain produce "
    "`Attempted to check equality of integer 1 with non-integer`, a message that names neither "
    "your variables nor the tagging.")
