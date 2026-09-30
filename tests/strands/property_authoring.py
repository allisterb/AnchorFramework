"""The property-authoring gate, checked without a model.

    python tests/strands/property_authoring.py

THE GATE IS THE FEATURE. Drafting a property module is a convenience; refusing to keep one that
says nothing is what makes the convenience safe. The literature's most-reported pathology in
agentic verification is a model asked to produce both an artifact and its specification
discovering that a trivial specification is the cheapest way to pass -- and the failure mode is a
property that is perfectly, uselessly true.

So the case that matters here is the negative one: a property that HOLDS and catches no mutant
must be REJECTED, and nothing must be written. A green run over a directory of true-and-empty
properties is exactly the false confidence this project exists to prevent.

The checker underneath is REAL. These run TLC.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from agent.author import assess, author, decides, preflight, score  # noqa: E402

POLICIES = REPO / "tests" / "policies"

# Parses, holds of every policy, and constrains nothing: its variable has no connection to the
# policy at all. The shape a model reaches for when a real claim is hard.
#
# TAKES THE NAME IT WILL BE WRITTEN UNDER, because TLA+ requires the module name to match its file
# name. A fixed name here would make this module fail to PARSE whenever the loop wrote it to a
# differently-named file, and a parse failure is a different rejection from the one being tested --
# the test would pass while never reaching the gate.
def trivial(name: str) -> str:
    return f"""---------------------------- MODULE {name} ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

VARIABLE x
Init == x = 1
Next == UNCHANGED x
Spec == Init /\\ [][Next]_x

AlwaysTrue == x = 1

=============================================================================
"""


TRIVIAL = trivial("Trivial")
TRIVIAL_CFG = "SPECIFICATION Spec\nINVARIANT AlwaysTrue\n"


# THE OTHER SHAPE OF EMPTY, and the reason there are two gates rather than one. This one is a
# tautology about the POLICY'S OWN DECISION -- it holds whatever the policy says, and whatever any
# broken version of it says. The static reader cannot see it, correctly: it does not evaluate
# `Decide`, because that is the entire authorization semantics and TLC is about to do it properly.
# So `preflight` lets it through and the MUTATION gate is what catches it.
#
# Keep both fixtures. A change that made either gate redundant would pass the other's test and
# quietly halve what the loop refuses.
def tautology(name: str) -> str:
    return f"""---------------------------- MODULE {name} ----------------------------
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>
Grants(input) == D!Decide(<<Request("Connect", input)>>, Policies, 1, AllValues)

Requests == {{[port |-> Num(22), origin |-> Str("local")]}}

VARIABLE req
Init == req \\in Requests
Next == UNCHANGED req
Spec == Init /\\ [][Next]_req

EitherWay == Grants(req) \\/ ~Grants(req)

=============================================================================
"""


TAUTOLOGY_CFG = "SPECIFICATION Spec\nINVARIANT EitherWay\n"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def scripted(*pairs):
    calls = {"n": 0}
    seen: list[str] = []

    def propose(vocab, intent, feedback):
        seen.append(feedback)
        i = min(calls["n"], len(pairs) - 1)
        calls["n"] += 1
        return pairs[i]

    propose.seen = seen                                 # type: ignore[attr-defined]
    return propose



def mutant_order() -> None:
    """The cap takes a PREFIX, so the order decides which rules ever get broken.

    `--mutants N` is `all_mutants[:N]` and defaults to 8. Grouped by rule, as this was, a 7-rule
    policy spent all 8 on rules 1 to 3 and never broke rules 4 to 7 -- so a property about a later
    rule survived every mutant tried and was rejected for "not constraining this policy at all",
    which is both false and the worst thing this gate can say.

    Measured on `examples/aws2/agent-policy.dw`: a property about `initiate_transfer` (rules 4 and
    5) caught 0 of the first 8 and 4 of all 21, every one of the four on rules 4 and 5. It cost
    three drafting attempts across two live sessions before the gate rather than the drafts was
    suspected.
    """
    from checker.properties import mutants                          # noqa: PLC0415

    rules = [{"index": i + 1, "effect": "permit" if i < 4 else "forbid",
              "actions": [f"act{i + 1}"], "cond": None} for i in range(7)]
    order = [what for what, _ in mutants(rules)]

    def rule_of(what: str) -> int:
        return int(re.match(r"rule (\d+)", what).group(1))

    first8 = {rule_of(w) for w in order[:8]}
    check("a cap of 8 breaks EVERY rule of a 7-rule policy, not just the first few",
          first8 == set(range(1, 8)), f"touched rules {sorted(first8)}")
    check("...and deletion comes first, being the damage any property should notice",
          all("deleted" in w for w in order[:7]), str(order[:7]))
    check("every rule is still mutated every way",
          len(order) == len({w for w in order}) and
          {rule_of(w) for w in order} == set(range(1, 8)), str(len(order)))


def main() -> int:
    # --- assess(): the gate's own logic ----------------------------------------------------------
    check("a module that did not run is rejected",
          bool(assess({"ran": False, "output": "boom"}, "INVARIANT X")))
    check("a .cfg naming no invariant is rejected",
          any("no INVARIANT" in c for c in assess({"ran": True, "holds": True, "caught": 3}, "")))
    check("holding while catching NOTHING is rejected",
          any("every broken version" in c
              for c in assess({"ran": True, "holds": True, "caught": 0}, "INVARIANT X")))
    check("holding and catching something is accepted",
          assess({"ran": True, "holds": True, "caught": 1}, "INVARIANT X") == [])
    # A property that FAILS on the real policy has already shown it discriminates -- that is a
    # finding about the policy, not a defect in the property, and must not be rejected.
    check("a property that fails on the real policy is accepted",
          assess({"ran": True, "holds": False, "caught": None}, "INVARIANT X") == [])

    # --- preflight(): the same refusal, reached by READING rather than by running ---------------
    # Nothing here starts TLC. That is the point: a draft rejected in a second is a round spent on
    # a better draft instead of on minutes of model checking that was never going to say anything.
    early = preflight(TRIVIAL, TRIVIAL_CFG, "Trivial.tla")
    check("a claim nothing can break is refused before TLC runs", bool(early), str(early))
    check("and the refusal names the claim and what it would forbid",
          bool(early) and "AlwaysTrue" in early[0] and "forbid" in early[0], str(early))
    check("a .cfg naming an undefined invariant is refused before TLC runs",
          any("does not define" in c
              for c in preflight(TRIVIAL, "SPECIFICATION Spec\nINVARIANT Absent\n", "Trivial.tla")))
    check("a real property passes preflight",
          preflight((POLICIES / "firewall.tla").read_text(encoding="utf-8"),
                    (POLICIES / "firewall.cfg").read_text(encoding="utf-8"), "firewall.tla") == [])
    # AND THE LIMIT OF READING, asserted rather than assumed: a tautology about the decision is
    # invisible here, because the decision is not evaluated. If this ever starts being caught by
    # `preflight`, the reader has begun evaluating the policy -- which is a much bigger claim than
    # this module makes, and should not happen silently.
    check("a tautology about the DECISION is invisible to reading alone",
          preflight(tautology("EitherWay"), TAUTOLOGY_CFG, "EitherWay.tla") == [],
          str(preflight(tautology("EitherWay"), TAUTOLOGY_CFG, "EitherWay.tla")))

    with tempfile.TemporaryDirectory(prefix="anchor-author-test-") as tmp:
        work = Path(tmp)
        shutil.copy(POLICIES / "firewall.dw", work)
        policy = work / "firewall.dw"

        good = (POLICIES / "firewall.tla").read_text(encoding="utf-8")
        good_cfg = (POLICIES / "firewall.cfg").read_text(encoding="utf-8")

        # --- THE ONE THAT MATTERS: true and empty is refused ------------------------------------
        out = work / "out"
        run = author(policy, "anything", scripted((TRIVIAL, TRIVIAL_CFG)),
                     rounds=1, mutants=4, out_dir=out, module_name="Trivial")

        check("a true-but-empty property is rejected", run.accepted is None,
              str(run.drafts[-1].complaints if run.drafts else "no drafts"))
        check("it was rejected for ranging over nothing that could break it",
              any("cannot fail" in c for c in run.drafts[0].complaints),
              str(run.drafts[0].complaints))
        check("and NOTHING was written", not (out / "Trivial.tla").exists())

        # --- the mutation gate, on the draft only IT can refuse ---------------------------------
        # This one runs TLC, on the policy and on each mutant, and is the slow half of the loop.
        empty = author(policy, "anything", scripted((tautology("EitherWay"), TAUTOLOGY_CFG)),
                       rounds=1, mutants=4, out_dir=out, module_name="EitherWay")

        check("a tautology about the decision is rejected by MUTATION", empty.accepted is None,
              str(empty.drafts[-1].complaints if empty.drafts else "no drafts"))
        check("and it was rejected for surviving every broken policy",
              any("every broken version" in c for c in empty.drafts[0].complaints),
              str(empty.drafts[0].complaints))
        check("nothing was written for it either", not (out / "EitherWay.tla").exists())

        # --- a real property is kept -------------------------------------------------------------
        # firewall.tla is named `firewall`, so it must be written as firewall.tla to parse.
        kept = author(policy, "local ssh allowed, outside refused",
                      scripted((good, good_cfg)), rounds=1, mutants=6,
                      out_dir=out, module_name="firewall")

        check("a property that holds AND discriminates is accepted", kept.accepted is not None,
              str(kept.drafts[-1].complaints if kept.drafts else "no drafts"))
        check("it caught at least one mutant", (kept.accepted.caught or 0) >= 1,
              str(kept.accepted.caught if kept.accepted else None))
        check("and it was written", (out / "firewall.tla").exists())

        # --- a rejected draft must not clobber a property already on disk ------------------------
        # The realistic disaster: a second attempt overwrites a module somebody wrote by hand, and
        # the failed draft is what is left behind.
        before = (out / "firewall.tla").read_text(encoding="utf-8")
        clobber = author(policy, "anything", scripted((trivial("firewall"), TRIVIAL_CFG)),
                         rounds=1, mutants=4, out_dir=out, module_name="firewall")

        check("a rejected draft is not kept", clobber.accepted is None)
        check("and the existing module is restored, not clobbered",
              (out / "firewall.tla").read_text(encoding="utf-8") == before)

        # --- the objection reaches the next round ------------------------------------------------
        proposer = scripted((trivial("firewall"), TRIVIAL_CFG), (good, good_cfg))
        two = author(policy, "x", proposer, rounds=2, mutants=6,
                     out_dir=out, module_name="firewall")
        check("a second draft is accepted after the first is refused", two.accepted is not None)
        check("and round 2 was told why round 1 failed",
              "cannot fail" in proposer.seen[1],                 # type: ignore[attr-defined]
              repr(proposer.seen[1][:90]))                        # type: ignore[attr-defined]

    # --- A MODULE THAT WILL NOT COMPILE IS NOT A PROPERTY THAT FAILED ---------------------------
    # This had no coverage and the gap was load-bearing. TLC exits non-zero whether a claim was
    # violated or the file never parsed, so the checker read a parse error as a violation: exit 1,
    # a BROKEN line, and the sentence "the policy does not mean what the property says it means"
    # -- a verdict about a policy that was never consulted. A real drafted module earned it over
    # one stray `*` in a comment. The checker now runs SANY first and answers "no verdict".
    broken = score(POLICIES / "firewall.dw", POLICIES / "firewall_unparseable.tla", mutants=1)
    check("a module that does not compile is not scored", broken["ran"] is False,
          str(broken.get("exitCode")))
    check("...and the checker says NO VERDICT rather than BROKEN", broken["exitCode"] == 2,
          str(broken.get("exitCode")))
    check("...and claims nothing about the policy",
          "does not mean what the property module says" not in broken["output"],
          broken["output"][-300:])

    said = assess(broken, (POLICIES / "firewall_unparseable.cfg").read_text(encoding="utf-8"))
    check("the complaint says nothing was checked",
          bool(said) and "nothing was checked" in said[0], str(said[:1]))
    # The drafter's next round can only fix this if it is told WHERE, and SANY is the only thing
    # that knows. A complaint without the location is one the loop cannot act on.
    # Not pinned to a line NUMBER: SANY reports where the parse gave up, which is the definition
    # after the stray character rather than the character itself, and adding a comment to the
    # fixture would move it. What must survive is that a location reaches the drafter at all.
    check("...and names where SANY choked, so a next round could fix it",
          bool(said) and "Parse Error" in said[0]
          and re.search(r"at line \d+, column \d+", said[0]) is not None, str(said[:1]))

    # --- AND A MODULE THAT COMPILES BUT DOES NOT EVALUATE ----------------------------------------
    # The same conflation one layer down, and it survived the SANY fix because SANY resolves NAMES
    # and not record FIELDS. A sweep of five real policies came back four-BROKEN on this: TLC died
    # with "Attempted to select nonexistent field", no claim was ever decided, and the checker
    # reported that the policy does not mean what the property says.
    crashed = score(POLICIES / "firewall.dw", POLICIES / "firewall_bad_field.tla", mutants=1)
    check("a module that dies while evaluating is not scored", crashed["ran"] is False,
          str(crashed.get("exitCode")))
    check("...and gets NO VERDICT rather than BROKEN", crashed["exitCode"] == 2,
          str(crashed.get("exitCode")))
    check("...and claims nothing about the policy",
          "does not mean what the property module says" not in crashed["output"],
          crashed["output"][-300:])
    check("...and names the field TLC choked on",
          "nonexistent field" in crashed["output"], crashed["output"][-300:])

    # --- THE DECISION PROBE: does the policy ever ANSWER differently? ------------------------------
    # The gate between the two above, and the one the aws2 sweep argued for. `preflight` asks
    # whether a claim's CONDITION can be satisfied; mutation asks whether the property notices the
    # policy breaking. Neither asks whether the policy's DECISION varies over the states the
    # property names -- and when it does not, every claim about a refusal holds having tested
    # nothing. Five drafted properties out of five failed exactly that way.
    varies, _ = decides(POLICIES / "firewall.dw", POLICIES / "firewall.tla")
    check("a property whose policy answers differently VARIES", varies == "varies", varies)

    # The same property, against the same policy with its PERMIT removed -- default-deny, so every
    # request it names is refused and `OutsideIsRefused` cannot fail.
    constant, why = decides(POLICIES / "firewall_noperm.dw", POLICIES / "firewall.tla")
    check("a policy that refuses everything the property names is CONSTANT",
          constant == "constant", constant)
    check("...and the diagnosis names the decision term and the likely cause",
          "Grants(req)" in why and "prerequisite" in why, why[-200:])

    # A gate that cannot read a module must not reject it: `skipped` is neither pass nor fail.
    # TRIVIAL calls no `D!Decide` at all, so there is no decision term to vary.
    with tempfile.TemporaryDirectory(prefix="anchor-probe-") as tmp:
        bare = Path(tmp) / "Trivial.tla"
        bare.write_text(TRIVIAL, encoding="utf-8")
        bare.with_suffix(".cfg").write_text(TRIVIAL_CFG, encoding="utf-8")
        nothing, _ = decides(POLICIES / "firewall.dw", bare)
    check("a module with no decision term is SKIPPED, not rejected", nothing == "skipped", nothing)

    # --- AND THE EVALUATOR, on the policy shape that broke it --------------------------------------
    # `--eval` answers "what IS this value" in a couple of seconds, and it silently stopped being
    # able to answer anything about a policy that both joins across value kinds and carries an
    # aggregate: TLC reported "Attempted to check equality of string ... with non-string: TRUE".
    # The generated eval module EXTENDED TLC instead of instancing it. Nothing noticed, because
    # the same expression checked as an INVARIANT evaluates correctly -- so every property run
    # passed while the evaluator was dead on exactly the policies worth evaluating.
    evaluated = subprocess.run(
        [sys.executable, str(REPO / "src" / "checker" / "properties.py"),
         str(POLICIES / "eval_join.dw"), "--property", str(POLICIES / "eval_join.tla"),
         "--eval", "<<Allowed(60), Allowed(3600)>>"],
        cwd=REPO, capture_output=True, text=True, timeout=900)
    said = evaluated.stdout + evaluated.stderr

    check("an expression over a joining, aggregating policy evaluates",
          "did not evaluate" not in said, said[-300:])
    # The VALUE, not merely the absence of an error: allowed inside the 15-minute window and
    # refused outside it. An evaluator that returns the wrong answer is worse than one that fails.
    check("...and returns the right values either side of the window",
          "<<TRUE, FALSE>>" in said, said[-300:])

    mutant_order()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("a drafted property is kept only if it could have failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
