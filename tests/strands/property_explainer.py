"""The plain-English property explainer, checked against real modules.

    python tests/strands/property_explainer.py

NOTHING HERE RUNS TLC, and that is the feature being tested rather than a shortcut. The explainer
is the checkpoint the literature puts at the property-formulation boundary -- the one step in the
pipeline nothing downstream verifies -- and it is only useful there if it is instant. A checkpoint
that costs minutes is a checkpoint people skip.

WHAT WOULD ROT SILENTLY. The English is generated, so a change to the renderer can turn a claim's
meaning inside out and still produce a fluent sentence: `~Grants(req)` glossed as "the policy GRANTS
it" reads perfectly and is exactly backwards. So the sense of the rendering is asserted here in
both directions, per shape, rather than the shape of the output.

And the counting, which is the other half. `A => B` tests nothing in any state where `A` is false,
so "applies to 3 of the 6" is the size of the experiment. Getting that wrong in the safe direction
(claiming more coverage than there is) is the failure that matters: it is the report telling a
reader a claim was tested when it was not.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from checker.explain import (Module, Unknown, explain, explain_file,  # noqa: E402
                             parse, render, show_value)

POLICIES = REPO / "tests" / "policies"
EXAMPLES = REPO / "examples" / "aws1"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def module(body: str, cfg: str, name: str = "M") -> Module:
    return Module(f"---- MODULE {name} ----\n"
                  f"EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest\n"
                  f"D == INSTANCE DogwoodSemantics WITH Cases <- << >>\n"
                  f"Grants(input) == D!Decide(<<Request(\"Connect\", input)>>, Policies, 1, AllValues)\n"
                  f"{body}\n"
                  f"====\n", cfg, f"{name}.tla")


def claim_named(x, name: str):
    return next(c for c in x.claims if c.name == name)


def main() -> int:
    # --- reading TLA+ ---------------------------------------------------------------------------
    # The reader either reads an expression or says it could not. A wrong reading is the one
    # outcome with no symptom, so the shapes these modules are written with are pinned here.
    check("an implication is read as one",
          parse("(a > 1) => ~F(a)")[:2] == ("bin", "=>"))
    check("`~` binds looser than `=`, as TLA+ says",
          parse("~x = 1") == ("un", "~", ("bin", "=", ("name", "x"), ("num", 1))))
    check("a tagged record is read",
          parse('[port |-> Num(22)]')[0] == "rec")
    check("a set comprehension is read",
          parse('{[p |-> Num(x)] : x \\in Ports}')[0] == "comp")
    check("an INSTANCE operator keeps its module",
          parse("D!Decide(a, b, c, d)")[1] == "D!Decide")

    # --- evaluating -----------------------------------------------------------------------------
    m = module("Minute == 60\nGaps == {1, 10 * Minute, 16 * Minute}\n", "")
    check("arithmetic over the module's own definitions is computed",
          show_value(m.value("Gaps")) == "{1, 600, 960}", show_value(m.value("Gaps")))

    # THE DISCIPLINE THE WHOLE THING RESTS ON. The policy decision is NOT evaluated here -- that is
    # the authorization semantics, it is TLC's job, and a reader that guessed at it would be a
    # second implementation of the thing under test, disagreeing silently.
    check("the policy's decision is UNKNOWN, never guessed",
          isinstance(m.evaluate(parse("Grants(r)"), {}), Unknown))
    check("and unknown propagates rather than defaulting",
          isinstance(m.evaluate(parse("Grants(r) /\\ 1 = 1"), {}), Unknown))
    check("but a conjunction with a FALSE half is still false",
          m.evaluate(parse("Grants(r) /\\ 1 = 2"), {}) is False)

    # --- the sense of the English -----------------------------------------------------------------
    x = explain(module(
        "Requests == {[port |-> Num(22)], [port |-> Num(443)]}\n"
        "VARIABLE req\n"
        "Init == req \\in Requests\n"
        "Next == UNCHANGED req\n"
        "Spec == Init /\\ [][Next]_req\n"
        "\n"
        "SshIsAllowed == (req.port = Num(22)) => Grants(req)\n"
        "\n"
        "HttpsIsRefused == (req.port = Num(443)) => ~Grants(req)\n",
        "SPECIFICATION Spec\nINVARIANT SshIsAllowed\nINVARIANT HttpsIsRefused\n"))

    allowed, refused = claim_named(x, "SshIsAllowed"), claim_named(x, "HttpsIsRefused")

    check("a claim that the policy must ALLOW forbids a refusal",
          "REFUSES" in allowed.forbids and "GRANTS" not in allowed.forbids, allowed.forbids)
    check("a claim that the policy must REFUSE forbids a grant",
          "GRANTS" in refused.forbids and "REFUSES" not in refused.forbids, refused.forbids)
    check("the tagging is not shown to the reader as content",
          "Num(" not in allowed.says and "22" in allowed.says, allowed.says)

    # --- the counting -----------------------------------------------------------------------------
    check("the states are enumerated from Init", len(x.states) == 2, str(x.states))
    check("a condition true in one state applies to one state",
          allowed.applies == ["req = [port |-> 22]"], str(allowed.applies))
    check("neither claim is vacuous", not x.vacuous, str([c.name for c in x.vacuous]))

    # --- the finding this exists to make ----------------------------------------------------------
    # A claim about a value the experiment never presents. It HOLDS, TLC reports it holding, and it
    # examined nothing. Same defect as a vacuous policy, same invisibility in a green run.
    empty = explain(module(
        "Requests == {[port |-> Num(22)]}\n"
        "VARIABLE req\n"
        "Init == req \\in Requests\n"
        "Next == UNCHANGED req\n"
        "Spec == Init /\\ [][Next]_req\n"
        "\n"
        "HttpsIsRefused == (req.port = Num(443)) => ~Grants(req)\n",
        "SPECIFICATION Spec\nINVARIANT HttpsIsRefused\n"))

    check("a claim whose condition no state satisfies is reported as vacuous",
          [c.name for c in empty.vacuous] == ["HttpsIsRefused"], str(empty.vacuous))
    check("and it says so in the rendering, loudly",
          "NOTHING THIS CLAIM RANGES OVER CAN BREAK IT" in render(empty))

    # The other shape: true by the module's own arithmetic, with no condition at all.
    settled = explain(module("VARIABLE x\nInit == x = 1\nNext == UNCHANGED x\n"
                             "Spec == Init /\\ [][Next]_x\n\nAlwaysTrue == x = 1\n",
                             "SPECIFICATION Spec\nINVARIANT AlwaysTrue\n"))
    check("a claim true by arithmetic alone is reported as vacuous",
          [c.name for c in settled.vacuous] == ["AlwaysTrue"], str(settled.vacuous))
    check("and the advice differs -- it is not about widening the domain",
          "asserts something about the MODEL" in render(settled))

    # AND THE LIMIT, asserted so that nobody reads a clean explanation as a clean bill of health.
    # A tautology about the decision is invisible to reading, because the decision is not read.
    blind = explain(module("Requests == {[port |-> Num(22)]}\nVARIABLE req\n"
                           "Init == req \\in Requests\nNext == UNCHANGED req\n"
                           "Spec == Init /\\ [][Next]_req\n\n"
                           "EitherWay == Grants(req) \\/ ~Grants(req)\n",
                           "SPECIFICATION Spec\nINVARIANT EitherWay\n"))
    check("a tautology about the DECISION is not caught by reading alone", not blind.vacuous,
          "if this now passes, the reader has started evaluating the policy")

    # --- what the .cfg does and does not say ------------------------------------------------------
    undefined = explain(module("VARIABLE x\nInit == x = 1\nNext == UNCHANGED x\n"
                               "Spec == Init /\\ [][Next]_x\n\nReal == x = 1\n",
                               "SPECIFICATION Spec\nINVARIANT Absent\n"))
    check("an invariant the module does not define is reported, not skipped",
          any(not c.defined and c.name == "Absent" for c in undefined.claims))
    check("and a claim the .cfg does not name is reported as unchecked",
          undefined.unchecked == ["Real"], str(undefined.unchecked))

    # --- failure is reported as failure -----------------------------------------------------------
    unreadable = explain(module("VARIABLE x\nInit == x \\in {1}\nNext == UNCHANGED x\n"
                                "Spec == Init /\\ [][Next]_x\n\n"
                                "Odd == LET y == x IN y = 1\n",
                                "SPECIFICATION Spec\nINVARIANT Odd\n"))
    odd = claim_named(unreadable, "Odd")
    check("an expression this reader cannot read is quoted, not explained",
          odd.says == "" and any("could not parse" in n for n in odd.notes), str(odd.notes))
    check("and an unreadable claim is never called vacuous", not odd.vacuous)

    # AN UNREADABLE *INIT* IS A DIFFERENT FAILURE, and it reached a person before it was caught.
    # This reader enumerates one variable ranging over a set of records; a module declaring SEVERAL
    # variables over named sets is outside that shape, so `states()` gives up and `total` is 0.
    # The rendering then said "applies to NONE of the 0 states" — a statement of fact about a
    # property nobody had measured, printed on all six claims of a module TLC had just checked and
    # found to HOLD over 48 states. The gate was right (`vacuous` requires `total > 0`, so it fails
    # open); only the words were wrong, which is worse than the reverse: nothing was blocked, and
    # the reader was told the opposite of the truth at the one checkpoint where a person decides.
    # THE BULLETED CONJUNCTION LIST, which is how Lamport writes one and what a drafter reaches
    # for. The parser here is infix and a leading `/\` has no left operand, so this raised
    # ParseError, `tree()` returned None, and the whole Init was reported unread.
    bulleted = explain(module(
        "Amounts == {500, 2500}\nGaps == {60, 1800}\n"
        "VARIABLE amount, gap\n"
        "Init ==\n    /\\ amount \\in Amounts\n    /\\ gap \\in Gaps\n"
        "Next == UNCHANGED <<amount, gap>>\n"
        "Spec == Init /\\ [][Next]_<<amount, gap>>\n\n"
        "Big == (amount = 2500) => (gap <= 1800)\n",
        "SPECIFICATION Spec\nINVARIANT Big\n"))
    check("a bulleted /\\ list is read the same as the inline form",
          len(bulleted.states) == 4, f"{len(bulleted.states)} states")
    check("...and the claim is counted over it",
          len(claim_named(bulleted, "Big").applies) == 2,
          str(claim_named(bulleted, "Big").applies))

    # WHY THAT MATTERS BEYOND THE RENDERING: `states()` giving up sets `total = 0`, and
    # `Claim.vacuous` requires `total > 0` — so the static vacuity gate was silently INACTIVE for
    # every module written this way. It failed open, which is the right direction, but it was not
    # doing its job and nothing said so.
    # The same fixture as the vacuity case above, with its Init written the other way round. If
    # the two ever disagree, the gate depends on layout — which is exactly the bug.
    empty_bulleted = explain(module(
        "Requests == {[port |-> Num(22)]}\n"
        "VARIABLE req\n"
        "Init ==\n    /\\ req \\in Requests\n"
        "Next == UNCHANGED req\n"
        "Spec == Init /\\ [][Next]_req\n"
        "\n"
        "HttpsIsRefused == (req.port = Num(443)) => ~Grants(req)\n",
        "SPECIFICATION Spec\nINVARIANT HttpsIsRefused\n"))
    check("...so a vacuous claim under a bulleted Init is now caught",
          [c.name for c in empty_bulleted.vacuous] == ["HttpsIsRefused"],
          str([c.name for c in empty_bulleted.vacuous]))

    # AND WHEN THE INIT GENUINELY CANNOT BE READ, say so rather than asserting a count. A NESTED
    # list stays unread on purpose: real bulleted lists are indentation-scoped, and a transform
    # that guessed at nesting could parse one into something that means something else. Failing to
    # read is recoverable; misreading is not.
    nested = explain(module(
        "VARIABLE a, b\n"
        "Init ==\n    /\\ a \\in {1, 2}\n    /\\ \\/ b = 1\n       \\/ b = 2\n"
        "Next == UNCHANGED <<a, b>>\nSpec == Init /\\ [][Next]_<<a, b>>\n\n"
        "Big == (a = 2) => (b = 1)\n",
        "SPECIFICATION Spec\nINVARIANT Big\n"))
    shown = render(nested)
    check("an Init this reader cannot enumerate leaves the state count unknown",
          claim_named(nested, "Big").total == 0 and not nested.states,
          f"total={claim_named(nested, 'Big').total}")
    check("...and is NOT reported as vacuous", not nested.vacuous,
          str([c.name for c in nested.vacuous]))
    # The load-bearing one. If this ever fails, the checkpoint is lying to somebody again: it told
    # a person "applies to NONE of the 0 states" on six claims of a property TLC had just checked
    # and found to HOLD over 48 states.
    check("...and the rendering does NOT say it applies to none of them",
          "NONE of the 0" not in shown and "NOT DETERMINED" in shown,
          next((line for line in shown.splitlines() if "applies" in line), ""))
    # Read as prose, whitespace collapsed: the rendering wraps its sentences to a column, and a
    # line break inside one is layout, not a change in what it says.
    flat = " ".join(shown.split())
    check("...but says plainly that the states were never counted",
          "never counted" in flat and "not a claim that it applies to none" in flat,
          next((line for line in shown.splitlines() if "applies" in line), ""))

    # --- the modules actually in the repo ---------------------------------------------------------
    # The fixtures above are written to exercise a shape. These are the real ones, and they are
    # what a reader will actually run this on.
    fw = explain_file(POLICIES / "firewall.tla")
    check("firewall.tla: both claims are read",
          [c.name for c in fw.claims] == ["LocalSshIsAllowed", "OutsideIsRefused"],
          str([c.name for c in fw.claims]))
    check("firewall.tla: 4 requests, and the outside claim applies to 2 of them",
          len(fw.states) == 4 and len(claim_named(fw, "OutsideIsRefused").applies) == 2,
          f"{len(fw.states)} states, {claim_named(fw, 'OutsideIsRefused').applies}")

    decay = explain_file(EXAMPLES / "TrustDecay10.tla")
    claim = claim_named(decay, "LosesWriteAfter10m")
    check("TrustDecay10.tla: the 10-minute claim applies to the three gaps past 600s",
          len(decay.states) == 6 and len(claim.applies) == 3,
          f"{len(decay.states)} states, {claim.applies}")
    check("TrustDecay10.tla: the window is shown as written AND as seconds",
          "10 * Minute (= 600)" in claim.forbids, claim.forbids)

    gate = explain_file(EXAMPLES / "TradeGate.tla")
    check("TradeGate.tla: the four claims its .cfg does not name are reported",
          len(gate.unchecked) == 4, str(gate.unchecked))
    check("TradeGate.tla: and the rendering says a property nobody listed is unchecked",
          "NOT named in the .cfg" in render(gate))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("what a property forbids is stated before it is checked, and counted honestly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
