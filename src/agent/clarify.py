"""Ambiguity reporting: when a request admits more than one policy, say so before writing one.

    python src/agent/clarify.py tests/policies/firewall.dw --ask "also open RDP in addition to SSH"

THE PROBLEM THIS ADDRESSES IS THE ONE NOTHING ELSE IN THE PIPELINE CAN. A verifier answers
questions about a policy that exists. It cannot tell you that the *request* was ambiguous, because
by the time it runs, a reading has already been chosen -- silently, by whatever wrote the policy.
The survey calls this the user-intent formalization gap and reports it as unsolved; Bedrock's
Automated Reasoning checks are the one place in the field that surfaces it, as a translation-
ambiguity finding carrying the competing interpretations rather than a silent pick among them.

"also open RDP in addition to SSH" is exactly that shape. In addition to *what* -- the same
authentication requirement? the same rate limit? a separate allowance of its own? The sentence does
not say, and an agent that picks one and proceeds has made a decision nobody saw.

WHAT ANCHOR ADDS, AND IT IS THE WHOLE POINT: the readings are not merely listed, they are CHECKED
AGAINST EACH OTHER. A model can always manufacture a distinction; whether one exists is a question
with an answer. Two readings that decide every session alike are not an ambiguity worth a person's
attention, however different they look -- and two that diverge come with the session that separates
them. So this reports ambiguity that is *material*, with the evidence, and stays quiet otherwise.

That asymmetry matters more than it sounds. An assistant that asks a clarifying question every time
trains people to click past it.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from agent.repair import run_checker  # noqa: E402

LABELS = "abcdefgh"


@dataclass
class Reading:
    """One way the request could be taken, and the policy it would produce."""

    label: str
    gloss: str
    candidate: str


@dataclass
class Distinction:
    """How a reading differs from the pivot, and the session that shows it."""

    reading: Reading
    verdict: str
    narrative: list[str] = field(default_factory=list)
    direction: str = ""            # "added" or "removed", whichever the witness came from


@dataclass
class Clarification:
    readings: list[Reading] = field(default_factory=list)
    distinctions: list[Distinction] = field(default_factory=list)
    unusable: list[tuple[Reading, str]] = field(default_factory=list)

    @property
    def material(self) -> bool:
        """Is there an ambiguity worth asking about? Only if two readings actually disagree."""
        return bool(self.distinctions)


def distinguish(readings: list[Reading], *, event_schema: Path | None = None,
                attempts: int | None = None, name: str = "policy.dw") -> Clarification:
    """Compare every reading against the first, and keep the ones that genuinely differ.

    AGAINST A PIVOT, NOT PAIRWISE, which is N-1 comparisons rather than N(N-1)/2. Sound because
    agreement is transitive within a fixed bound: if b decides every session as a does, and c does
    too, then b and c agree with each other. It buys grouping, not a b-versus-c witness -- and the
    question being answered is "does this ambiguity matter", for which the pivot is enough.
    """
    result = Clarification(readings=readings)
    if len(readings) < 2:
        return result

    with tempfile.TemporaryDirectory(prefix="anchor-clarify-") as tmp:
        work = Path(tmp)
        paths = {}
        for r in readings:
            p = work / f"{r.label}-{name}"
            p.write_text(r.candidate, encoding="utf-8")
            paths[r.label] = p

        pivot = readings[0]
        for r in readings[1:]:
            out = run_checker(paths[r.label], against=paths[pivot.label],
                              event_schema=event_schema, attempts=attempts)
            if out.get("_failed"):
                # A reading the checker cannot answer about is not evidence of anything. Recorded
                # as unusable rather than quietly dropped, because "I could not tell" and "they
                # are the same" are different answers and only one of them is reassuring.
                result.unusable.append((r, out.get("_why", "the checker produced no verdict")))
                continue

            verdict = out.get("verdict", "")
            if verdict == "EQUIVALENT":
                continue

            # Prefer the ADDED witness: what a reading lets through that the pivot does not is
            # the half somebody needs to have chosen deliberately.
            side = "added" if out.get("added") else "removed"
            detail = out.get(side) or {}
            result.distinctions.append(Distinction(
                reading=r, verdict=verdict, direction=side,
                narrative=detail.get("narrative") or [detail.get("witness", "")]))

    return result


def model_readings(model=None, most: int = 3):
    """Ask a model for the distinct readings of a request. The only part that costs money.

    It is asked for readings that would produce DIFFERENT policies, not merely different wordings,
    because a distinction the checker then finds immaterial is a question asked for nothing. It
    will still produce some -- that is what the checking is for.
    """
    import json

    from strands import Agent

    from agent.policy_agent import build_model

    agent = Agent(model=model or build_model(), callback_handler=None, system_prompt=(
        "You read a request to change a Dogwood (.dw) authorization policy and identify the "
        "genuinely different ways it could be taken.\n\n"
        "Return ONLY a JSON array. Each element is an object with:\n"
        '  "gloss"  - one sentence, in plain language, saying what this reading means\n'
        '  "policy" - the complete revised .dw file text under that reading\n\n'
        "Give the readings that would produce DIFFERENT policies -- different decisions for some "
        "request -- not different phrasings of the same one. If the request has only one sensible "
        "reading, return a single element. Never more than the number asked for."))

    def propose(current: str, request: str, n: int) -> list[tuple[str, str]]:
        text = str(agent(
            f"The current policy:\n\n{current}\n\nThe request: {request}\n\n"
            f"At most {min(n, most)} readings.")).strip()

        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            # One reading, unusable as a comparison, rather than a crash: a malformed reply means
            # we learned nothing about ambiguity, which is not the same as there being none.
            return []
        return [(str(i.get("gloss", "")), str(i.get("policy", "")))
                for i in items if isinstance(i, dict) and i.get("policy")]

    return propose


def clarify(policy: Path, request: str, propose, *, most: int = 3,
            event_schema: Path | None = None, attempts: int | None = None) -> Clarification:
    """Find the readings of `request`, and report only those that decide something differently."""
    current = policy.read_text(encoding="utf-8")
    proposed = propose(current, request, most)
    readings = [Reading(label=LABELS[i], gloss=gloss, candidate=text)
                for i, (gloss, text) in enumerate(proposed[:most])]
    return distinguish(readings, event_schema=event_schema, attempts=attempts, name=policy.name)


def report(c: Clarification, request: str) -> str:
    """The clarification as a person should read it. Empty when there is nothing to ask."""
    if not c.readings:
        return ""

    if not c.material:
        if len(c.readings) < 2:
            return ""
        lines = [f'I considered {len(c.readings)} readings of "{request}" and they come out as the',
                 "same policy within the bound -- every session either would allow, the other",
                 "allows too. So it does not matter which you meant."]
        if c.unusable:
            lines += ["", "One reading could not be checked, so this does not cover it:"]
            lines += [f"  ({r.label}) {r.gloss}" for r, _ in c.unusable]
        return "\n".join(lines)

    lines = [f'"{request}" could mean more than one thing, and the difference is real:', ""]
    for r in c.readings:
        lines.append(f"  ({r.label}) {r.gloss}")

    pivot = c.readings[0].label
    for d in c.distinctions:
        verb = "newly allows" if d.direction == "added" else "no longer allows"
        lines += ["", f"  ({d.reading.label}) is {d.verdict} than ({pivot}) -- it {verb}:"]
        lines += [f"      {line}" for line in d.narrative if line]

    lines += ["", "Which did you mean?"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policy", type=Path, help="the .dw policy the request is about")
    ap.add_argument("--ask", required=True, help="the request, in words")
    ap.add_argument("--most", type=int, default=3, help="readings to consider (default 3)")
    ap.add_argument("--event-schema", type=Path, default=None)
    ap.add_argument("--attempts", type=int, default=None)
    args = ap.parse_args()

    print(f"reading {args.policy.name}: {args.ask}\n(this makes live model calls)\n",
          file=sys.stderr)

    c = clarify(args.policy, args.ask, model_readings(most=args.most), most=args.most,
                event_schema=args.event_schema, attempts=args.attempts)

    text = report(c, args.ask)
    if not text:
        print("no ambiguity worth raising: only one reading was proposed.", file=sys.stderr)
        return 0

    print(text)
    # 0 when there is nothing to ask, 3 when a person should choose. A distinct code so a script
    # can branch on "needs a human" without parsing prose.
    return 3 if c.material else 0


if __name__ == "__main__":
    sys.exit(main())
