"""The bounded repair loop: propose, check, feed back, revise -- with the checker as the oracle.

    python src/agent/repair.py tests/policies/dead_forbid.dw --ask "delete the rule that does nothing"
    python src/agent/repair.py firewall.dw --ask "also open RDP" --against firewall.dw --no-widening

WHY THE LOOP IS CODE AND THE MODEL IS NOT. The pattern the field has converged on -- AutoRocq
against Rocq (arXiv:2511.17330), Baldur against Isabelle, neuro-formal verification against Dafny
(arXiv:2608.21516) -- is `propose -> check -> feedback -> repair`. Its two load-bearing parts are a
CORRECTNESS ORACLE and feedback rich enough to act on. Anchor is already the oracle. What was
missing was the loop around it.

The division matters more than it looks:

    the model      proposes policy TEXT, and nothing else
    this file      decides what is checked, with what bounds, and whether the result is acceptable

An agent that could choose its own acceptance criteria would eventually choose ones it meets. That
is not a hypothetical. Lahiri (arXiv:2608.21516) ran an agent in a repair loop against Dafny with
nothing held fixed, and it "proved" 98% of known-buggy programs. Of those false proofs:
- 57% rewrote the code;
- 35% restated the goal with invented helpers;
- 8% rested on an explicit assumption.

His fix is to freeze everything the proof is ABOUT -- the translated source, the library theory, the
precondition, the goal -- and re-check it mechanically every round. TLA-Prover (arXiv:2606.06133)
names the TLA+ form of the same failure: an always-true invariant passes TLC on every problem.
AxDafny (arXiv:2606.32007) defends a Dafny repair loop the same way. Code checks that the original
requires/ensures clauses survive, and rejects proof bypasses (`assume`, `{:axiom}`, `{:verify false}`,
`{:extern}`) before the verifier runs.

Here the frozen parts are `--property`, `--against` and `--no-widening`: arguments to this
function, evaluated after the model has spoken and never shown to it as something editable.

BOUNDED, and the bound is reported. A loop that cannot fail is a loop that will not stop; `rounds`
caps it, and running out is an outcome that gets said plainly rather than dressed up as the best
attempt so far.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from agent import invoke                               # noqa: E402

CHECKER = invoke.CHECKER          # kept importable; the path now lives in `invoke`

# Verdicts that mean the edit allows something the baseline did not. Widening is not wrong by
# itself -- "also open the RDP port" is a request to widen -- so it is a failure only when the
# caller said it should be.
WIDENING = ("MORE PERMISSIVE", "INCOMPARABLE")


@dataclass
class Round:
    """One turn of the loop: what was proposed, what the checker said, and why it was rejected."""

    number: int
    candidate: str
    accepted: bool
    complaints: list[str] = field(default_factory=list)
    prop: dict | None = None                # the stated property's verdict, when one was given
    rules: dict | None = None
    comparison: dict | None = None
    error: str | None = None

    def feedback(self) -> str:
        """What the next proposal is told. The complaints, and nothing else.

        Deliberately not a pep talk and not a suggested fix: the checker found a specific thing,
        and passing that through unembellished is what keeps the loop grounded in the oracle
        rather than in our guess about what the model should do next.
        """
        return "\n".join(f"- {c}" for c in self.complaints)


@dataclass
class RepairRun:
    """Every round, and whether one was accepted. `accepted` is None when the bound ran out."""

    rounds: list[Round] = field(default_factory=list)
    accepted: Round | None = None

    @property
    def exhausted(self) -> bool:
        return self.accepted is None and bool(self.rounds)


def run_checker(policy: Path, *, against: Path | None = None, event_schema: Path | None = None,
                attempts: int | None = None, timeout: int = 900) -> dict:
    """One checker invocation, as structured output. Never raises on a policy it dislikes.

    A REFUSAL IS DATA HERE, not an exception. The loop's whole job is to react to the checker
    disliking something, so "this policy uses a construct outside the modelled subset" has to
    arrive as a complaint the next round can act on rather than as a crash.
    """
    args = [str(policy), "--json"]
    if against is not None:
        args += ["--against", str(against)]
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]
    if attempts is not None:
        args += ["--attempts", str(attempts)]

    proc = invoke.checker(args, timeout=timeout)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        # Exit code 2 is the checker's "I produced no verdict"; anything else is a genuine
        # failure to run. Both become a complaint, but they are not the same complaint.
        why = (proc.stderr or proc.stdout).strip()
        return {"_failed": True, "_exitCode": proc.returncode,
                "_why": why[-1200:] or "the checker produced no output"}


def check_property(policy: Path, module: Path, *, event_schema: Path | None = None,
                   max_fields: int | None = None, timeout: int = 900) -> dict:
    """Does the candidate still satisfy the stated property?

    A SECOND INVOCATION, and it has to be. `--property` REPLACES the derived questions rather than
    adding to them -- the checker returns the property verdict and never looks at whether a rule
    went inert -- so asking for both in one call silently drops one of them. And a property run
    prints prose, so `--json` on it produces nothing to parse: the loop read that as "the checker
    could not produce a verdict" and rejected every candidate, including the ones that satisfied
    the property. A gate that says no whatever happens is not a gate.
    """
    args = [str(policy), "--property", str(module)]
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]
    if max_fields is not None:
        args += ["--max-fields", str(max_fields)]

    proc = invoke.checker(args, timeout=timeout)
    out = (proc.stdout + proc.stderr).strip()

    # 0 holds, 1 broken. Anything else is the checker declining to answer, which is neither.
    if proc.returncode not in (0, 1):
        return {"_failed": True, "_exitCode": proc.returncode,
                "_why": out[-1200:] or "the checker produced no output"}

    from checker.witness import violations                       # noqa: PLC0415

    return {"held": proc.returncode == 0, "output": out,
            "violations": [{"invariant": v.invariant, "state": v.printed}
                           for v in violations(out)]}


def assess(rules: dict, comparison: dict | None, *, no_widening: bool,
           prop: dict | None = None) -> list[str]:
    """What is wrong with this candidate, in the words the next round will be given.

    THE CRITERIA LIVE HERE, in code, and the model never sees them as an editable input. Each
    complaint names the rule and quotes the checker, so a proposal can act on it without having to
    interpret prose about it.
    """
    complaints: list[str] = []

    if rules.get("_failed"):
        complaints.append(
            "the checker could not produce a verdict for this policy. It said:\n"
            f"{rules['_why']}")
        return complaints

    for rule in rules.get("rules", []):
        verdict = rule["verdict"]
        if verdict in ("VACUOUS", "REDUNDANT", "DEAD"):
            complaints.append(
                f"{verdict} {rule['effect']} #{rule['index']} (action {', '.join(rule['actions'])}): "
                f"{rule['note']}. A rule that changes no verdict is not a control.")

    # `unknown` is not a defect -- it is the absence of an answer, and treating it as a defect
    # would have the model rewrite rules that are probably fine.
    if rules.get("unknown"):
        complaints.append(
            f"no verdict was reached for rule(s) {rules['unknown']} within the search budget. "
            "That is not a finding about them; leave them alone unless something else is wrong.")

    # THE STATED PROPERTY, which the model cannot reach and must not be able to weaken. This is the
    # criterion the literature warns about most: asked to satisfy a property it cannot satisfy, a
    # model's cheapest move is to edit the property. Here it is an argument, evaluated after the
    # model has spoken, and a violation blocks acceptance outright.
    if prop is not None:
        if prop.get("_failed"):
            complaints.append("the stated property could not be checked against this candidate. "
                              f"The checker said:\n{prop['_why']}")
        elif not prop.get("held"):
            for v in prop.get("violations") or [{"invariant": "the property", "state": {}}]:
                where = ", ".join(f"{k} = {x}" for k, x in (v.get("state") or {}).items())
                complaints.append(
                    f"the candidate does not satisfy {v['invariant']}"
                    + (f", which is violated at {where}" if where else "")
                    + ". That is a stated requirement, not a preference: an edit that breaks it "
                      "is not acceptable however well it answers the request.")

    if comparison is not None and not comparison.get("_failed"):
        verdict = comparison.get("verdict")
        if no_widening and verdict in WIDENING:
            added = comparison.get("added") or {}
            story = "\n  ".join(added.get("narrative") or [added.get("witness", "")])
            complaints.append(
                f"this is {verdict} than the policy it replaces, and it was required not to add "
                f"permissions. It newly allows:\n  {story}")

    return complaints


def repair(policy: Path, request: str, propose, *, rounds: int = 3, no_widening: bool = False,
           against: Path | None = None, event_schema: Path | None = None,
           property_module: Path | None = None, attempts: int | None = None,
           on_round=None) -> RepairRun:
    """Ask for an edit, check it, and hand the objections back -- up to `rounds` times.

    `propose(current_text, request, feedback) -> str` returns candidate `.dw` text. Injected
    rather than built in, so the LOOP is testable without a model, credentials or a bill: the
    mechanics are where the mistakes live, and they should not be verifiable only on the runs
    somebody is willing to pay for. `model_proposer` builds the real one.

    `on_round` is called with each `Round` as it completes, so a caller can show the loop running.
    That is not decoration -- an agent that visibly corrects itself is making a different claim
    from one that produces a right answer, and the correction is the part worth watching.
    """
    original = policy.read_text(encoding="utf-8")
    baseline = against if against is not None else policy
    run = RepairRun()
    feedback = ""
    current = original

    with tempfile.TemporaryDirectory(prefix="anchor-repair-") as tmp:
        candidate_path = Path(tmp) / policy.name

        for n in range(1, rounds + 1):
            candidate = propose(current, request, feedback)
            candidate_path.write_text(candidate, encoding="utf-8")

            rules = run_checker(candidate_path, event_schema=event_schema, attempts=attempts)
            comparison = None
            if not rules.get("_failed"):
                comparison = run_checker(candidate_path, against=baseline,
                                         event_schema=event_schema, attempts=attempts)

            # Only when the candidate is readable at all: a property run against a policy the
            # checker already refused would add a second complaint about the same cause.
            prop = None
            if property_module is not None and not rules.get("_failed"):
                prop = check_property(candidate_path, property_module, event_schema=event_schema)

            complaints = assess(rules, comparison, no_widening=no_widening, prop=prop)
            this = Round(number=n, candidate=candidate, accepted=not complaints,
                         complaints=complaints, rules=rules, comparison=comparison, prop=prop)
            run.rounds.append(this)
            if on_round:
                on_round(this)

            if this.accepted:
                run.accepted = this
                return run

            # The next proposal starts from THIS candidate, not from the original: the loop is a
            # refinement, and handing back the original each round would ask the model to redo
            # work it already got right and lose the parts that were fine.
            current = candidate
            feedback = this.feedback()

    return run


def model_proposer(model=None):
    """A proposer backed by a language model. The only part of the loop that costs money.

    The prompt is thin for the same reason the reviewer's is: it says what to return and what not
    to, and leaves the judgement to the model. It does NOT restate the acceptance criteria,
    because the criteria are checked mechanically afterwards -- telling the model what will be
    measured invites it to write for the measurement.
    """
    from strands import Agent

    from agent.policy_agent import build_model

    agent = Agent(model=model or build_model(), callback_handler=None, system_prompt=(
        "You edit Dogwood (.dw) authorization policies.\n\n"
        "Return ONLY the complete text of the revised policy file. No explanation, no commentary, "
        "no markdown fence. The reply is written to a .dw file exactly as you give it.\n\n"
        "Preserve comments and structure that the request does not bear on. Change as little as "
        "the request requires."))

    def propose(current: str, request: str, feedback: str) -> str:
        prompt = f"The current policy:\n\n{current}\n\nThe request: {request}"
        if feedback:
            prompt += ("\n\nYour previous attempt was checked by a model checker and rejected:\n"
                       f"{feedback}\n\nRevise it.")
        text = str(agent(prompt)).strip()

        # Models fence code even when told not to. Stripping it here rather than insisting in the
        # prompt: one line of code beats one more instruction nobody can enforce.
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return text.strip() + "\n"

    return propose


def show(round_: Round) -> None:
    """Print one round as it happens, so the loop can be watched rather than summarised."""
    status = "ACCEPTED" if round_.accepted else "rejected"
    print(f"\n--- round {round_.number}: {status} " + "-" * 40, file=sys.stderr)
    if round_.complaints:
        for c in round_.complaints:
            print(f"  {c}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policy", type=Path, help="the .dw policy to edit")
    ap.add_argument("--ask", required=True, help="what to change, in words")
    ap.add_argument("--rounds", type=int, default=3, help="how many attempts before giving up")
    ap.add_argument("--against", type=Path, default=None,
                    help="the baseline to compare against (default: the policy as it is now)")
    ap.add_argument("--no-widening", action="store_true",
                    help="reject any candidate that allows something the baseline did not. Use "
                         "when the request is meant to REMOVE access, or to leave it unchanged")
    ap.add_argument("--event-schema", type=Path, default=None)
    ap.add_argument("--property", type=Path, default=None, dest="property_module",
                    help="a TLA+ property the result must satisfy. IMMUTABLE: the model proposes "
                         "policy text only and never sees this as something it may change")
    ap.add_argument("--attempts", type=int, default=None, help="session length bound")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="write the accepted policy here (default: print it)")
    args = ap.parse_args()

    print(f"repairing {args.policy.name}: {args.ask}\n"
          f"up to {args.rounds} round(s); each one makes live model calls\n", file=sys.stderr)

    run = repair(args.policy, args.ask, model_proposer(), rounds=args.rounds,
                 no_widening=args.no_widening, against=args.against,
                 event_schema=args.event_schema, property_module=args.property_module,
                 attempts=args.attempts, on_round=show)

    if run.accepted is None:
        print(f"\nNO ACCEPTED CANDIDATE after {len(run.rounds)} round(s).", file=sys.stderr)
        print("The last attempt's objections stand; it is NOT the best answer so far, it is an\n"
              "answer that failed. Raise --rounds, or the request may need a person.",
              file=sys.stderr)
        return 1

    print(f"\naccepted at round {run.accepted.number} of {len(run.rounds)}", file=sys.stderr)
    if args.out:
        args.out.write_text(run.accepted.candidate, encoding="utf-8")
        print(f"written to {args.out}", file=sys.stderr)
    else:
        print(run.accepted.candidate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
