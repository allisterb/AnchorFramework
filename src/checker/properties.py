"""Model-check an arbitrary Dogwood policy file for vacuity, one permit at a time.

    python src/checker/properties.py tests/policies/approval_gate_response.dw

A permit is VACUOUS when no session can make it grant anything. That is not a weak control, it is
zero control, and nothing about the policy's text says so -- it parses, it validates, and it
authorizes nothing. AWS's own material says the automated-reasoning tools Cedar provides do not
answer this for the temporal part of the language.

WHAT MAKES THIS MORE THAN A DEMO. Nobody hand-writes a model of the policy. The `.dw` text goes
through `translator` -- the parser whose reading agrees with the reference implementation on 914
recorded corpus pairs -- into a generated `PolicyUnderTest.tla`, and `Vacuity.tla` evaluates it with
`DogwoodSemantics!Decide`, the same evaluator validated against those pairs and against the live
engine on the `error`-event scenarios.

    any .dw ──> translator  ──> PolicyUnderTest.tla ──┐
                                                        ├──> TLC, once per permit
                              Vacuity.tla ──────────────┘

READ THE RESULT BACKWARDS. TLA+ has no `EF`, so reachability is asked by checking the negation and
reading the counterexample as the witness. A TLC *violation* means the permit CAN grant -- the good
outcome. A clean run means it never does. This script inverts that before printing, because the raw
reading is a trap.

The bound is real: VACUOUS means "no session of up to `--attempts` attempts makes it fire", not
"never". Raise it to trade runtime for confidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPECS = REPO / "specs" / "policy" / "TemporalPolicy"

sys.path.insert(0, str(REPO / "src"))

from translator import (DECISION_KIND, DEFAULT_MAX_WINDOW, Unsupported, apply_pins,  # noqa: E402
                        find_jar, generate_policy_module, parse_policies, parse_schema, run_eval,
                        run_sany, run_tlc, narrate, stamp_keys, vocabulary, witness_events)
from translator.agentcore import (AGENTCORE_SCHEMA, is_agentcore, refuse_unsound,  # noqa: E402
                                  rejections, uses_agentcore_fields)
from translator.parse import DEFAULT_SCOPE_FIELDS  # noqa: E402

# Event kinds AgentCore records. `request` is the decision event -- the point authorization runs --
# and the outcome is `response` when the action completed, `error` when it was denied.


# Exit codes, which callers branch on. 0 answered, 1 a --property claim is BROKEN, 2 no verdict,
# 3 could not run -- and this fourth one, which is neither a pass nor a failure of the POLICY.
WeakProperty = 4


# ---------------------------------------------------------------------------- checking
CONFIG = """SPECIFICATION Spec

\\* A session ends after MaxAttempts, which has no successor action.
CHECK_DEADLOCK FALSE

CONSTANTS
    MaxAttempts = {attempts}
    MaxAmount = {amount}
    Target = {target}

INVARIANT TypeOK

\\* MEANT TO FAIL. A violation is the witness session; a clean run means there is none.
\\* See the header of Vacuity.tla for why the reading is inverted.
INVARIANT {invariant}
"""


def progress(message: str) -> None:
    """A line on stderr saying which TLC run is starting, when a caller asked for them.

    Asked for with ANCHOR_PROGRESS. The audit and the CLI set it, because a policy set with many
    rules is minutes of TLC and silence reads as a hang. The MCP server does not: an agent reads the
    answer, not a running commentary, and the stderr it parses for a refusal stays as it was.
    """
    if os.environ.get("ANCHOR_PROGRESS"):
        print(message, file=sys.stderr, flush=True)


@contextmanager
def workdir(args, prefix: str):
    """Where a run's generated TLA+ lives -- a temp directory, or `--keep DIR` if one was asked for.

    THE ARTIFACTS ARE THE ARGUMENT. A verdict from a model checker is only as good as the model,
    and until now the model was written into a temp directory and deleted on the way out, so
    nobody could examine the thing the answer came from. That is a bad position for a project
    whose whole claim is that its answers are checkable: "trust me, TLC said so" is the opposite
    of formal methods.

    With `--keep` the directory holds `PolicyUnderTest.tla` (generated from the policy text),
    `Vacuity.tla`, `DogwoodSemantics.tla`, the `.cfg` naming the invariant and the bounds, and the
    raw TLC output per run. That is enough to re-run the check by hand and to disagree with it.
    """
    if args.keep:
        # RESOLVED, because TLC runs with this directory as its cwd and is given `-metadir
        # <dir>/states`. A relative path there resolves against the cwd -- which is this same
        # directory -- so `--keep examples/aws1/traces/derived` produced
        # `derived/examples/aws1/traces/derived/states/...`, the whole path repeated inside itself.
        keep = args.keep.resolve()
        keep.mkdir(parents=True, exist_ok=True)
        try:
            yield keep
        finally:
            # TLC's own scratch: fingerprint sets and state queues, megabytes of them, and not
            # evidence of anything. The verdict, the model and the raw output are what a reader
            # came for.
            shutil.rmtree(keep / "states", ignore_errors=True)
        return
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(tmp)


def keep_run(args, work: Path, name: str, out: str) -> None:
    """Preserve one TLC run: the config it actually used, and the output it produced.

    THE CONFIG IS COPIED, NOT REBUILT. `check_one` writes `Vacuity.cfg` before each run, so the
    file on disk is the one TLC read -- copying it cannot drift from what ran, whereas formatting
    a second copy from the same template could, and would do it silently. Called immediately after
    each run, because the next one overwrites `Vacuity.cfg`.

    No-op without `--keep`.
    """
    if not args.keep:
        return
    (work / f"{name}.tlc.txt").write_text(out, encoding="utf-8")
    cfg = work / "Vacuity.cfg"
    if cfg.exists():
        shutil.copyfile(cfg, work / f"{name}.cfg")


def keep_readme(args, work: Path, runs: list[tuple[str, str]]) -> None:
    """Explain the kept directory well enough that someone can re-run it and disagree.

    A directory of `.tla` files is not reproducibility on its own. TLC takes its configuration
    from a file named after the MODULE, so a config kept under a run's own name cannot be used
    where it lies -- and a reader would have to work that out from an error message.

    `runs` is (config stem, module stem). They differ for the built-in questions, which all run
    the `Vacuity` module under several configs, and coincide for a property module, which brings
    its own correctly-named config and needs no copying. The commands below reflect which.
    """
    if not args.keep:
        return
    # The REAL jar, not a plausible-looking name. It carries its version -- tla2tools-1.7.4.jar --
    # and a README promising reproducibility with a path that does not exist is worse than one
    # that says nothing.
    try:
        jar = str(find_jar())
    except Exception:                                             # noqa: BLE001
        jar = "lib/tla2tools-<version>.jar   (not found when this was written)"

    against = getattr(args, "against", None)
    lines = [
        "# The model this verdict came from",
        "",
        f"Generated by `src/checker/properties.py` from `{args.policy.name}`"
        + (f" against `{against.name}`" if against else "")
        + ". Everything TLC",
        "was given is here, so the run can be repeated and the answer argued with.",
        "",
        "| file | |",
        "|---|---|",
    ]

    # Only what is actually here. A property run brings its own module and never copies
    # `Vacuity.tla`, so listing it unconditionally would describe a file the reader cannot find --
    # a small lie, in a document whose whole job is to be checkable.
    described = [
        ("PolicyUnderTest.tla", "generated from the policy TEXT -- the actions, event kinds and"
                                " field domains the policy actually reads, plus the rules as records"),
        ("Vacuity.tla", "the session model and the built-in questions asked of it"),
        ("DogwoodSemantics.tla", "the evaluator, shared with the differential tests"),
    ]
    lines += [f"| `{name}` | {what} |" for name, what in described if (work / name).exists()]
    lines += [
        "| `*.cfg` | the configuration each run used, copied as it ran |",
        "| `*.tlc.txt` | the raw TLC output for each run, counterexample included |",
        "",
        "## Re-running",
        "",
    ]

    needs_copy = [(cfg, mod) for cfg, mod in runs if cfg != mod]
    if needs_copy:
        lines += [
            "**TLC reads its config from a file named after the module**, so these have to be"
            " copied into",
            "place first -- they cannot be passed under their own names:",
            "",
        ]
    lines.append("```bash")
    for cfg, mod in runs:
        if cfg == mod:
            lines.append(f"java -cp {jar} tlc2.TLC -config {cfg}.cfg {mod}")
        else:
            lines.append(f"cp {cfg}.cfg {mod}.cfg && java -cp {jar} tlc2.TLC -config {mod}.cfg {mod}")
    lines += [
        "```",
        "",
        "## Reading the result BACKWARDS",
        "",
        "The built-in questions are asked as invariants that are **meant to fail**. TLA+ has no"
        " existential",
        "path quantifier, so reachability is asked by checking the negation: a *violation* is the"
        " witness,",
        "and a clean run is the claim of absence. `properties.py` inverts this before printing,"
        " which is",
        "why the raw output reads the opposite way round.",
        "",
        "| invariant | a violation means |",
        "|---|---|",
        "| `NeverFires` | the target rule CAN grant something -- it is live rather than VACUOUS |",
        "| `NeverMatters` | deleting the target rule WOULD change a verdict -- it is load-bearing |",
        "| `NeverWidened` | the first policy permits a session the second denies -- the edit ADDED"
        " a permission |",
        "| `NeverNarrowed` | the first denies a session the second permits -- it REMOVED one |",
        "",
        "**A property module of your own is the exception**: it is meant to HOLD, and a violation"
        " names the",
        "request that breaks your claim. No inversion there.",
        "",
        "## What the bound was",
        "",
        f"`MaxAttempts = {args.attempts}`, `MaxAmount = {args.amount}`. Every negative answer is"
        " bounded by",
        "those and by nothing else; raising them trades runtime for confidence. `Target` selects"
        " which rule",
        "a run is about -- `0` means the second policy file. Each `.cfg` carries the values that"
        " run used.",
        "",
    ]
    (work / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_one(work: Path, target: int, attempts: int, amount: int,
              invariant: str = "NeverFires",
              smoke: int | None = None) -> tuple[bool | None, str]:
    """Returns (a witness exists, TLC output). Raises if TLC could not answer.

    `NeverFires`   a witness means the permit CAN grant something -- it is live.
    `NeverMatters` a witness means deleting the rule WOULD change a verdict -- it is load-bearing.

    THREE answers, not two:

        True   a witness was found. SOUND either way -- a witness is a witness however it was
               reached, so a smoke run that finds one has settled the question.
        False  no witness EXISTS. Only exhaustive search can say this.
        None   no witness was found by a random walk, which says nothing about whether one exists.

    `smoke` is a number of random behaviours. It can only ever return True or None, because the
    claims False supports -- VACUOUS, REDUNDANT, DEAD -- are claims of ABSENCE, and a random walk
    cannot establish absence. Reporting one from a smoke run would be the silent-wrong-answer
    direction, and it would tell someone to delete a working rule.
    """
    (work / "Vacuity.cfg").write_text(
        CONFIG.format(attempts=attempts, amount=amount, target=target, invariant=invariant),
        encoding="utf-8")

    # A fixed seed, so a verdict is reproducible. TLC randomises the seed by default, which would
    # make `unknown` mean something different on every run and a reported witness unreproducible.
    extra = ["-simulate", f"num={smoke}", "-seed", "0"] if smoke else None
    ok, out = run_tlc("Vacuity", work, work, extra)

    if f"Invariant {invariant} is violated" in out:
        return True, out
    if ok and "Model checking completed" in out:
        return False, out

    # Simulation ran to the end of its budget and found nothing. Positive evidence that it RAN --
    # not merely the absence of a violation -- so a crash cannot arrive here dressed as "unknown".
    if smoke and ok and "Random Simulation" in out and "Finished in" in out:
        return None, out

    # Anything else -- a parse error, an unsupported construct reaching TLC, a TypeOK failure --
    # is not an answer. Never let it read as "vacuous"; that is the silent-wrong-answer direction.
    raise RuntimeError(f"TLC could not answer for permit {target}:\n{out}")


def witness(out: str) -> str:
    """The session TLC found, as the actions attempted in order.

    Only the LAST state block is scanned. TLC prints the whole `trace` variable at every state, so
    each event appears once more for every state that follows it -- reading the full output turns a
    two-attempt witness into "Approve -> Approve -> Trade" and overstates what it took to fire.
    """
    states = re.split(r"^State \d+: ", out, flags=re.MULTILINE)
    final = states[-1] if len(states) > 1 else out
    actions = re.findall(r'action \|-> "([A-Za-z0-9_]+)",\s*kind \|-> "' + DECISION_KIND + '"', final)
    return " -> ".join(actions) if actions else "(see TLC output, --verbose)"



# ---------------------------------------------------------------------------- blame
#
# A verdict says a rule is inert. It does not say WHICH PART of it made it inert, and that is the
# part somebody has to fix. "This forbid never denies anything" sends a reader back to re-read
# their own condition; "it cannot fire because `port > 1024` and `port == 3389` cannot both hold"
# is an instruction.
#
# The method is unsat-core minimisation, one level of decomposition below the rule: drop conjuncts
# and re-ask, keeping only those whose presence is still enough to kill it. Greedy, so the result
# is 1-MINIMAL -- removing any single term from the answer revives the rule -- which is not the
# same as globally smallest, and is the honest thing to claim for N runs rather than 2^N.


def conjuncts(cond) -> list[dict]:
    """The top-level conjuncts of a condition. Empty when there is no condition to blame."""
    if not isinstance(cond, dict) or cond.get("op") == "true":
        return []
    if cond.get("op") == "and":
        return list(cond["args"])
    return [cond]


def rebuild(terms: list[dict]) -> dict:
    """A condition from a subset of conjuncts. No terms means an unconditional rule."""
    if not terms:
        return {"op": "true", "args": []}
    return terms[0] if len(terms) == 1 else {"op": "and", "args": terms}


def duration(seconds: int) -> str:
    """A window as the policy author wrote it: 86400 -> 24h, 900 -> 15m, 30 -> 30s.

    The parse holds seconds, which is right for the evaluator and wrong for a reader -- nobody
    recognises their own 24-hour window as `86400s`, and a blame report they cannot match to their
    own text is a blame report they will not act on.
    """
    # Hours, never days: a 24-hour window is written `24h` in every policy in either corpus, and
    # echoing it back as `1d` is a unit the author has to translate before recognising their own.
    for size, unit in ((3600, "h"), (60, "m")):
        if seconds and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def describe_term(term) -> str:
    """One conjunct, close to how it was written. Falls back rather than guessing.

    This reads the PARSED form, not the source text, because the parse is what was checked -- a
    conjunct quoted from the file could differ from the one the verdict is about if the parser
    read it differently, and that is precisely the disagreement worth not hiding.
    """
    if not isinstance(term, dict):
        return str(term)

    # `term` wraps a temporal position; unwrap it, keeping the operator and window.
    if term.get("op") == "term":
        inner = term.get("term", {})
        op, window = inner.get("op", ""), inner.get("window", 0)
        atom = describe_term(inner.get("atom", inner))
        if op == "since":
            return f"... since within {duration(window)} {atom}"
        if op in ("formerly", "previous") and window:
            return f"{op} within {duration(window)} {atom}"
        return atom

    op = term.get("op")
    field = term.get("field", "")
    if op == "pred":
        # An event match: the action, the kind, and any first-order joins. This is the commonest
        # term in a temporal policy, and it used to render as `<pred>` -- which named the shape of
        # the parse tree and nothing a reader could act on.
        pred = term.get("pred", {})
        # A scope bind reads as written -- `eventResource: resource` -- rather than as the side and
        # internal field name the model keeps it under.
        binds = ", ".join(
            f"{b['as']}: {b.get('name') or b.get('value')}" if b.get("as") else
            f"{b.get('side', '?')}.{b.get('field', '?')}: {b.get('name') or b.get('value')!r}"
            for b in pred.get("binds", []))
        return (f"{pred.get('action', '?')}::{pred.get('kind', '?')}"
                + (f"{{ {binds} }}" if binds else ""))
    if op == "cmp":
        return f"input.{field} {term.get('cmp', '?')} {term.get('value')}"
    if op == "cmpvar":
        return f"input.{field} {term.get('cmp', '?')} {term.get('other', 'a bound value')}"
    if op == "like":
        pattern = "".join("*" if p is None else str(p) for p in term.get("pattern", []))
        return f'input.{field} like "{pattern}"'
    if op == "inrange":
        net = ".".join(str(o) for o in term.get("net", []))
        return f"input.{field} in {net}/{term.get('prefix', '?')}"
    if op == "agg":
        return f"{term.get('agg', {}).get('kind', 'count')}(...) {term.get('cmp', '?')} {term.get('value')}"
    if op == "not":
        return "not (" + "; ".join(describe_term(a) for a in term.get("args", [])) + ")"
    if op in ("and", "or"):
        joiner = " && " if op == "and" else " || "
        return "(" + joiner.join(describe_term(a) for a in term.get("args", [])) + ")"

    # Something this renderer does not model. Named by its operator rather than silently omitted,
    # because a blame report missing a term is a blame report that is wrong.
    return f"<{op}{' on input.' + field if field else ''}>"


def still_inert(work: Path, policies: list[dict], vocab: dict, keys, index: int,
                terms: list[dict], invariant: str, args) -> bool:
    """Is rule `index` still inert when its condition is only `terms`?

    The VOCABULARY IS NOT RECOMPUTED. It comes from the whole policy as written, so dropping a
    conjunct does not shrink the request space along with it -- otherwise removing the term that
    mentions a field would also remove the values that field can take, and the rule would look
    revived because the question got smaller.
    """
    trial = list(policies)
    trial[index - 1] = {**policies[index - 1], "cond": rebuild(terms)}
    (work / "PolicyUnderTest.tla").write_text(
        generate_policy_module(args.policy, trial, vocab, keys=keys), encoding="utf-8")
    # `check_one` returns (verdict, output) -- UNPACKED, because comparing the tuple itself to
    # False is always false, which made every trial look revived and left the core never shrinking.
    # False means no witness: still inert. True means it fired, None cannot occur -- blame is not
    # attempted under --smoke, because it would be minimising against an answer that is not one.
    found, _ = check_one(work, index, args.attempts, args.amount, invariant)
    return found is False


def blame(work: Path, policies: list[dict], vocab: dict, keys, index: int,
          verdict: str, args) -> tuple[str, list[str]]:
    """Why rule `index` is inert: ("structural" | "terms" | "none", the terms to blame).

    Costs one TLC run per conjunct plus one, so a two-term rule costs three. Only ever run for a
    rule already found inert, which is the rare case rather than the common one.
    """
    terms = conjuncts(policies[index - 1].get("cond"))
    # REDUNDANT and DEAD are both "deleting it changes nothing"; VACUOUS is "it never fires".
    invariant = "NeverFires" if verdict == "VACUOUS" else "NeverMatters"

    if not terms:
        return "structural", []

    # First the question that makes the rest worth asking: would it be inert with NO condition?
    # If so the condition is not the reason, and minimising within it would produce a confident
    # answer pointing at the wrong thing.
    rule = f"{policies[index - 1]['effect']} #{index}"
    progress(f"  TLC  {rule} is {verdict}: would it still be with no condition at all?")
    if still_inert(work, policies, vocab, keys, index, [], invariant, args):
        return "structural", []

    core = list(terms)
    for term in terms:
        shown = describe_term(term)
        progress(f"  TLC  {rule} is {verdict}: is it still, without "
                 f"`{shown if len(shown) <= 60 else shown[:57] + '...'}`?")
        trial = [t for t in core if t is not term]
        if still_inert(work, policies, vocab, keys, index, trial, invariant, args):
            core = trial

    # Restore the module, so anything written afterwards -- `--keep`, a later rule's run -- sees
    # the policy as written rather than the last trial.
    (work / "PolicyUnderTest.tla").write_text(
        generate_policy_module(args.policy, policies, vocab, keys=keys), encoding="utf-8")

    return ("terms", [describe_term(t) for t in core]) if core else ("none", [])


# ---------------------------------------------------------------------------- custom properties
def prove(args, policies: list[dict], vocab: dict, keys: list[str] | None = None) -> int:
    """Check the author's claim about what this policy means."""
    print(f"{args.policy.name} against {args.property_module.name}: "
          f"{len(policies)} rule(s)\n")

    # BEFORE the run, not after it, because after it the answer is already framing the question.
    # A reviewer shown "every claim holds" and then asked what the claim was has been told the
    # conclusion first; shown what the claim FORBIDS and then the verdict, they can still object.
    if args.explain:
        from checker.explain import explain_file, render  # noqa: PLC0415  -- one direction only
        print(render(explain_file(args.property_module)) + "\n")

    with workdir(args, "anchor-prove-") as work:
        (work / "PolicyUnderTest.tla").write_text(
            generate_policy_module(args.policy, policies, vocab, keys=keys), encoding="utf-8")
        shutil.copyfile(SPECS / "DogwoodSemantics.tla", work / "DogwoodSemantics.tla")

        # WHAT IS THIS VALUE? Asked of the property module, so its own definitions are in scope.
        if args.eval:
            shutil.copyfile(args.property_module, work / args.property_module.name)
            cfg = args.property_module.with_suffix(".cfg")
            if cfg.exists():
                shutil.copyfile(cfg, work / cfg.name)

            ok, out = run_eval(args.eval, args.property_module.stem, work)
            print(f"  {args.eval}\n")
            print("\n".join(f"      {line}" for line in out.splitlines()[:60]))
            if not ok:
                print("\nThe expression did not evaluate. TLC's output is above; nothing was checked.")
            return 0 if ok else 2

        # DOES IT COMPILE? A second, against minutes for the check it would otherwise fail inside.
        #
        # The generated module has to exist first, which is why this lives here rather than in a
        # verb of its own: a property module EXTENDS `PolicyUnderTest`, and that file is built from
        # the policy. Parsing the module on its own would report the vocabulary missing, which is
        # true and useless.
        # ALWAYS, not only under --parse. A module that does not compile is not a property that
        # failed, and TLC cannot tell you the difference: it exits non-zero either way, and the
        # violation path below then prints a counterexample it does not have and concludes that
        # "the policy does not mean what the property says it means". That sentence is a verdict
        # about the POLICY, drawn from a run in which the policy was never consulted -- the exact
        # conflation of "we could not ask" with "it is broken" that this module exists to prevent.
        # It cost a real drafted module a BROKEN verdict over one stray `*` in a comment.
        #
        # A second, against minutes for the run it would otherwise fail inside.
        shutil.copyfile(args.property_module, work / args.property_module.name)
        compiles, sany = run_sany(args.property_module.stem, work)
        keep_run(args, work, f"{args.property_module.stem}.sany", sany)

        if not compiles:
            print(f"  {args.property_module.name} DOES NOT COMPILE. SANY says:\n")
            print("\n".join(f"      {line}" for line in sany.splitlines()[:30]))
            print("\nNothing was checked. A module that does not compile has no verdict to give,\n"
                  "and the claims in it have not been tested.")
            return 2

        if args.parse:
            print(f"  {args.property_module.name} compiles against {args.policy.name}'s "
                  f"vocabulary.\n")
            print("That is not a check of the policy. It says the module parses, resolves every\n"
                  "name it uses, and is ready to be run -- nothing about whether its claims hold.")
            return 0

        if args.decision_probe:
            cfg = args.property_module.with_suffix(".cfg")
            shutil.copyfile(cfg, work / cfg.name)
            verdict, why = probe_decision(work, args.property_module,
                                          cfg.read_text(encoding="utf-8"))
            print(f"  decision over this module's states: {verdict.upper()}\n")
            print(f"      {why}")
            if verdict == "error":
                print("\nNothing was checked, and this is a defect in the module rather than a "
                      "verdict about\nthe policy. The commonest cause is ordering a TAGGED value -- "
                      "`Num(22)` is a record,\nnot the integer 22, so `x <= 22` and `x <= Num(22)` "
                      "both fail. Compare the number inside:\n`x.v <= 22`. (`=` and `#` do take two "
                      "tagged values: `s = Str(\"a1\")`.)")
                return 2
            if verdict == "constant":
                print("\nNOTHING THIS PROPERTY MODULE SAYS CAN BE TESTED against this policy set. Give the "
                      "module\nstates the policy answers differently, or the claims below it are "
                      "true of a\ndecision that never changes.")
                return WeakProperty
            if verdict == "varies":
                print("\nThe policy answers differently across the states this module ranges "
                      "over, so its\nclaims are about something that can go either way. That is "
                      "a precondition for\nchecking them, not a verdict on them.")
            return 0

        held, out = check_property(work, args.property_module)

        # The property module brings its own correctly-named .cfg, which `check_property` has
        # already copied in, so nothing needs renaming for a re-run.
        if args.keep:
            (work / f"{args.property_module.stem}.tlc.txt").write_text(out, encoding="utf-8")
            keep_readme(args, work,
                        [(args.property_module.stem, args.property_module.stem)])

    if held:
        print("  every claim holds over every request the property module names.\n")
        print("That is not a proof about requests it does not name. A property module ranges over\n"
              "what it says it ranges over, and nothing warns you when that is less than you meant.")
        if args.mutation_score:
            return mutation_report(args, policies, vocab, keys, held=True)
        return 0

    # A MODULE THAT CRASHED IS NOT A PROPERTY THAT FAILED, and TLC exits non-zero either way.
    # SANY clears the module's syntax before this point, but a module that COMPILES can still die
    # while evaluating -- "Attempted to select nonexistent field" is the common one, from a field
    # name that does not exist on a record. There is no violated invariant in that output, and
    # reporting it as BROKEN asserts that the policy does not mean what the property says, drawn
    # from a run in which no claim was ever decided. Four of five policies in a real sweep came
    # back BROKEN this way.
    violations = violated_by(out)
    if not violations:
        print(f"  {args.property_module.name} COMPILED BUT DID NOT EVALUATE. TLC says:\n")
        for line in [ln for ln in out.splitlines() if ln.startswith("Error:")][:6]:
            print(f"      {line}")
        print("\nNothing was checked. No claim was decided either way, so there is no verdict\n"
              "about the policy here -- the module needs fixing first.")
        return 2

    source = args.property_module.read_text(encoding="utf-8", errors="replace")
    for v in violations:
        print(f"  BROKEN  {v}")

        # THE CLAIM ITSELF, quoted from the module. A violation reports a NAME and a state, and
        # neither says which way the failure goes: `KeepsWriteWhileAdvisorEngaged` being violated
        # at `gap = 1` means the policy DENIED where the claim expected allow, and a reader who
        # cannot see the invariant will guess -- an agent asked this question guessed the opposite.
        # The definition is three lines away in a file the caller may not be able to open.
        for line in definition_of(source, v.split(" is violated")[0].split()[-1]):
            print(f"        {line}")

    print("\nThe policy set does not mean what the property module says it means. The state above\n"
          "is the request that breaks the claim, and the claim is quoted beneath it -- read the two\n"
          "together, because a violated invariant says which direction failed only when you can\n"
          "see what it asserted.")

    # THE SAME FINDING IN THE POLICY'S OWN LANGUAGE. The state above is a TLA+ variable belonging
    # to a module a tool may have drafted; this is the session it stands for, in Dogwood, with the
    # reference engine's verdict on it where the engine is available to ask.
    if args.witness:
        from checker.witness import confirm, reading_schema, render  # noqa: PLC0415  -- one direction only

        # THE EVENT SCHEMA GOES WITH IT. TLC found this counterexample under whatever reading the
        # schema imposes, and replaying it against the engine's default would be answering about a
        # different deployment -- confidently, and with the reference implementation's authority.
        # With no schema file the reading is still a definite one, pinned or --unpinned, and the
        # engine is handed it as a file rather than left to its own default.
        with tempfile.TemporaryDirectory(prefix="anchor-reading-") as scratch:
            found = confirm(args.policy, args.property_module, out,
                            keep=args.keep / "witness" if args.keep else None,
                            event_schema=args.event_schema or reading_schema(
                                "unpinned" if args.unpinned else "pinned", Path(scratch)))
        if found:
            print("\nIn Dogwood's own terms:\n")
            print(render(found))
    if args.mutation_score:
        mutation_report(args, policies, vocab, keys, held=False)
    return 1


# ---------------------------------------------------------------------------- permissiveness
# The four verdicts, and the vocabulary is deliberately Cedar Analysis's own: `cedar-lean-cli
# analyze compare` returns Equivalent / More Permissive / Less Permissive / Incomparable. Agreeing
# with the neighbouring tool costs nothing and means a reader who knows one knows the other.
#
# What differs is the DOMAIN. Cedar compares a policy as a function of one REQUEST. This compares
# over SESSIONS, because a Dogwood decision can depend on what happened earlier -- and a rate limit
# or an approval window is invisible to any comparison that looks at one request at a time.
VERDICTS = {
    (False, False): ("EQUIVALENT",
                     "no session of up to {attempts} attempts tells them apart"),
    (True,  False): ("MORE PERMISSIVE",
                     "this edit ADDS permissions"),
    (False, True):  ("LESS PERMISSIVE",
                     "this edit REMOVES permissions"),
    (True,  True):  ("INCOMPARABLE",
                     "this edit both adds and removes permissions -- usually a mistake"),
}


def direction(found, out: str) -> dict | None:
    """One direction of a comparison, as structured data. None when nothing was found.

    `witness` is the one-line summary a person reads; `session` is the same counterexample as
    events, which is what an agent needs -- a repair loop has to know the INPUT VALUES that
    reached the bad decision, and "ApproveSale -> SellShares" does not carry them.
    """
    if not found:
        return None
    events = witness_events(out)
    return {
        "witness": witness(out),
        "session": events,
        # The same session as sentences. Carried rather than left for the caller to compose,
        # so that an agent quoting Anchor and a person reading it see the SAME words -- two
        # renderings of one verdict is one more than the number that can be checked.
        "narrative": narrate(events),
    }


def compare(args, policies: list[dict], other: list[dict], vocab: dict,
            keys: list[str] | None = None, reading: str = "") -> int:
    """Is this policy wider than the one it replaces, narrower, both, or neither?

    TWO TLC RUNS, NOT ONE, and the reason is TLC rather than the question: it stops at the first
    violated invariant, so asking both directions at once would answer whichever it reached first
    and silently drop the other. A run per direction also yields a witness per direction, which is
    what the answer is actually made of -- "you now allow this" is useful, "they differ" is not.

    WHICH DIRECTION IS THE DANGEROUS ONE. A permission removed is a support ticket: somebody is
    locked out, they complain, it gets fixed. A permission silently added is an incident. So the
    widening witness is reported first and at greater length, even though the question people ask
    out loud is usually the other one.
    """
    tier = f", SMOKE: {args.smoke} random sessions, not exhaustive" if args.smoke else ""
    if not args.json:
        print(f"{args.policy.name} vs {args.against.name}: "
              f"{len(policies)} rule(s) vs {len(other)}, bound {args.attempts} attempts{tier}\n")

    with workdir(args, "anchor-compare-") as work:
        (work / "PolicyUnderTest.tla").write_text(
            generate_policy_module(args.policy, policies, vocab, other, args.against.name, keys),
            encoding="utf-8")
        for module in ("Vacuity.tla", "DogwoodSemantics.tla"):
            shutil.copyfile(SPECS / module, work / module)

        # Target = 0 selects `Other` -- the second file -- as the set compared against.
        wider, wider_out = check_one(work, 0, args.attempts, args.amount,
                                     "NeverWidened", args.smoke)
        keep_run(args, work, "NeverWidened", wider_out)

        narrower, narrower_out = check_one(work, 0, args.attempts, args.amount,
                                           "NeverNarrowed", args.smoke)
        keep_run(args, work, "NeverNarrowed", narrower_out)

        # The .cfg left on disk is whichever ran LAST, which would misrepresent the first run to
        # anyone re-running by hand. `keep_run` copied each one as it went; this names the modules
        # they belong to.
        keep_readme(args, work, [("NeverWidened", "Vacuity"), ("NeverNarrowed", "Vacuity")])

        if args.verbose and not args.json:
            for label, out in (("NeverWidened", wider_out), ("NeverNarrowed", narrower_out)):
                print(f"    ---- {label} ----")
                print("\n".join(f"    {line}" for line in out.splitlines()))

    # A smoke run answers True or None and NEVER False, because it cannot establish absence. The
    # unknown must not collapse into "no": "this edit adds no permissions" is exactly the sentence
    # somebody would ship on.
    unknown = wider is None or narrower is None
    verdict, gloss = ("UNKNOWN", "a random walk cannot rule a difference out") if unknown \
        else VERDICTS[(wider, narrower)]

    if args.json:
        print(json.dumps({
            "policy": args.policy.name,
            "against": args.against.name,
            # Flattened: the prose form is wrapped for a terminal, and embedded newlines in a
            # JSON string are just noise to whatever is parsing this.
            "reading": " ".join(reading.split()),
            "bound": {"attempts": args.attempts, "amount": args.amount,
                      "exhaustive": not args.smoke,
                      "randomSessions": args.smoke or None},
            "verdict": verdict,
            # Null means "not found", which under --smoke is NOT the same as "does not exist".
            # `bound.exhaustive` is what says which of the two this null is.
            "added": direction(wider, wider_out),
            "removed": direction(narrower, narrower_out),
            "artifacts": str(args.keep) if args.keep else None,
        }, indent=2))
        return 0

    print(f"  {verdict}   {gloss.format(attempts=args.attempts) if not unknown else gloss}\n")

    if unknown:
        found = [what for what, v in (("adds", wider), ("removes", narrower)) if v]
        print(f"  a random walk found {' and '.join(found) or 'no difference'}, which settles "
              f"{'that much' if found else 'nothing'}.\n")
        print("A smoke run can only ever FIND a difference, never rule one out. Re-run without\n"
              "--smoke for a verdict that distinguishes EQUIVALENT from not-yet-found.")
        return 0

    if wider:
        print("  ADDED     a session this policy permits and the old one denies:\n")
        for line in narrate(witness_events(wider_out),
                            f"{args.against.name} DENIES this") or [f"  {witness(wider_out)}"]:
            print(f"              {line}")
        print("\n            This is the direction worth reading twice -- it is what the edit\n"
              "            grants that nobody asked it to grant.")
    if narrower:
        if wider:
            print()
        print("  REMOVED   a session the old policy permitted and this one denies:\n")
        for line in narrate(witness_events(narrower_out),
                            f"{args.policy.name} DENIES this") or [f"  {witness(narrower_out)}"]:
            print(f"              {line}")

    if not wider and not narrower:
        print("Within the bound the two files are interchangeable: every session either set\n"
              "allows, the other allows too. That is a statement about DECISIONS, not about\n"
              "text -- the files may well read very differently.")
    else:
        print("\n--json gives the witness as structured events rather than this summary, and\n"
              "--keep DIR writes the model, the .cfg and the raw TLC output for re-running.")

    if args.keep:
        print(f"\nartifacts: {args.keep}")

    print(f"\nBOUNDED. Sessions of up to {args.attempts} attempts, and the comparison is driven\n"
          "along histories the NEW set produces -- sound because the two agree up to the first\n"
          "point they disagree, which is the point this reports. A difference appearing only in\n"
          "longer sessions is not excluded by this run.")
    return 0


# ---------------------------------------------------------------------------- custom properties
def decision_call(source: str) -> str | None:
    """The module's own decision term -- `Grants(req)`, `Allowed(s)`, `TradeAllowed(gap)`.

    Found rather than configured, because every property module names it something different. The
    DEFINITION is whichever one calls `D!Decide`; the TERM is how a claim applies it, and it is the
    application we want -- its arguments are the module's variables, so evaluating it over the
    module's own states is exactly the question.

    Returns None when it cannot be found, and the caller must then SKIP rather than reject: a gate
    that cannot read a module has learned nothing about it.
    """
    # COMMENTS OUT FIRST. `Grants` appears in the prose above its own definition at least as often
    # as in a claim, and a bare name matched there yields an operator used without its arguments --
    # a probe module that will not parse, reported as "the module did not evaluate", which is true
    # of the probe and false of the module.
    source = re.sub(r"\(\*.*?\*\)", " ", source, flags=re.DOTALL)
    source = re.sub(r"\\\*[^\n]*", "", source)

    lines = source.splitlines()
    name, takes_args = None, False
    for i, line in enumerate(lines):
        if (m := re.match(r"^(\w+)\s*(\([^)]*\))?\s*==", line)):
            body = [line]
            for nxt in lines[i + 1:]:
                if re.match(r"^\w+\s*(?:\([^)]*\))?\s*==|^=====", nxt):
                    break
                body.append(nxt)
            if "D!Decide" in "\n".join(body):
                name, takes_args = m.group(1), bool(m.group(2))
                break
    if name is None:
        return None

    # How a CLAIM applies it. The parentheses are BALANCED rather than matched to the first `)` --
    # `Grants([port |-> Num(22)])` closes twice -- and a definition is told from an application by
    # what FOLLOWS it, not by what precedes it: `Claim == Allowed(s)` has `==` on its left and is
    # an application, which an earlier version of this skipped and then reported "skipped" on the
    # one module that had already found a real violation.
    for m in re.finditer(rf"\b{re.escape(name)}\b\s*(\()?", source):
        end = m.end()
        if takes_args and not m.group(1):
            continue                                    # a mention, not an application
        if m.group(1):
            depth, i = 1, m.end()
            while i < len(source) and depth:
                depth += (source[i] == "(") - (source[i] == ")")
                i += 1
            if depth:
                continue
            end = i
        # `==` and not `====...`: the module TERMINATOR also begins with two equals signs, so the
        # last claim in a file -- which is exactly where the decision term usually is -- read as a
        # definition and the probe reported "skipped" on every module.
        if re.match(r"==(?!=)", source[end:end + 40].lstrip()):
            continue                                    # a definition of it, not a use
        return source[m.start():end]
    return None


PROBE = """---------------------------- MODULE DecisionProbe ----------------------------
EXTENDS {module}

\\* Does the policy's answer VARY over the states this property ranges over? Each of these is
\\* checked on its own; a violation means the decision was not constant in that direction.
NotAlwaysRefused == {call}
NotAlwaysGranted == ~({call})
============================================================================
"""


def probe_decision(work: Path, module: Path, cfg_text: str) -> tuple[str, str]:
    """Is the policy's decision CONSTANT over every state this property ranges over?

    THE DEFECT THIS CATCHES, and it is the commonest way an agent-authored property comes back
    worthless: the claims are well formed, their conditions match states, the module compiles --
    and the policy refuses every single request the property names, so every refusal claim holds
    without testing anything. Five drafted properties out of five failed this way on one real
    policy set, and the only thing that caught them was mutation scoring: a TLC run per mutant, to
    conclude "it survived every mutant", which is a symptom rather than the cause.

    Two invariant runs over the module's own Init answer it directly, in seconds. Checking the
    module's states rather than a request set we invent is the point -- the question is about the
    property as written.
    """
    call = decision_call(module.read_text(encoding="utf-8", errors="replace"))
    if call is None:
        return "skipped", ("no definition in this module calls D!Decide, so there is no decision "
                           "term to vary. Nothing was concluded.")

    (work / "DecisionProbe.tla").write_text(
        PROBE.format(module=module.stem, call=call), encoding="utf-8")

    # The module's own CONSTANTS and SPECIFICATION, with its invariants replaced by ours.
    kept = [ln for ln in cfg_text.splitlines() if not ln.strip().startswith(("INVARIANT", "PROPERTY"))]
    verdicts = {}
    for which in ("NotAlwaysRefused", "NotAlwaysGranted"):
        (work / "DecisionProbe.cfg").write_text(
            "\n".join(kept + [f"INVARIANT {which}", ""]), encoding="utf-8")
        held, out = run_tlc("DecisionProbe", work, work)

        # AN EVALUATION ERROR IS NOT A VERDICT, and it looks exactly like one here: TLC exits
        # non-zero whether the invariant was violated or the module died computing it, so both
        # probes coming back "not held" would read as "varies" -- the healthiest answer there is,
        # reported for a module that cannot be evaluated at all. Distinguished by whether a
        # violation was actually named.
        if not held and not violated_by(out):
            errors = [ln for ln in out.splitlines() if ln.startswith("Error:")][:4]
            return "error", ("the module compiled but did not evaluate, so nothing about the "
                             "policy's decision could be established. TLC says:\n        "
                             + "\n        ".join(errors))
        verdicts[which] = held

    # HELD means the invariant was never violated -- so the decision never went the other way.
    if verdicts["NotAlwaysRefused"] and verdicts["NotAlwaysGranted"]:
        return "unknown", f"`{call}` could not be evaluated over this module's states"
    if verdicts["NotAlwaysRefused"]:
        return "constant", (
            f"the policy GRANTS every request this property module names: `{call}` is true in every "
            f"state the module ranges over. A claim about what is refused therefore cannot fail, "
            f"whatever it says")
    if verdicts["NotAlwaysGranted"]:
        return "constant", (
            f"the policy REFUSES every request this property module names: `{call}` is false in every "
            f"state the module ranges over. A claim about what is refused therefore holds without "
            f"testing anything. The usual cause is a session that omits a prerequisite the policy "
            f"set requires -- a verification, an approval, a prior read -- so the request is "
            f"denied before the rule this property module is about is ever reached")
    return "varies", f"`{call}` is true in some of this module's states and false in others"


def check_property(work: Path, module: Path, said: str | None = None) -> tuple[bool, str]:
    """Run the author's own property module against the generated policy records.

    Returns (it holds, TLC output). A violation is the ANSWER here, not an inversion: unlike the
    vacuity questions, which ask for reachability and so read a counterexample as the witness, a
    property is meant to hold and TLC's counterexample names the request that breaks it.
    """
    cfg = module.with_suffix(".cfg")
    if not cfg.exists():
        raise Unsupported(
            f"{module.name} needs a companion {cfg.name} naming the invariants to check, e.g.\n"
            f"      SPECIFICATION Spec\n"
            f"      INVARIANT YourClaim\n"
            f"    Naming them is deliberate: a claim nobody listed is a claim nobody checked")

    shutil.copyfile(module, work / module.name)
    shutil.copyfile(cfg, work / cfg.name)
    # `said` is the caller's own line for this run, where it knows better -- a mutant, say.
    progress(said or f"  TLC  {module.name}: every claim, in every state it ranges over")
    return run_tlc(module.stem, work, work)


# A state conjunct as TLC prints it: a variable name, then =, then its value.
VARIABLE_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]* = ")


def definition_of(module: str, name: str) -> list[str]:
    """The lines of `name == ...` in a TLA+ module, with the comment above it.

    Returns [] when the name is not defined there -- which is the right answer for an invariant
    TLC names but the module does not define, and never a guess.
    """
    lines = module.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(rf"^{re.escape(name)}\s*==", l.strip())), None)
    if start is None:
        return []

    # The body runs to the first blank line: TLA+ definitions here are one expression, and a
    # blank line is how this codebase separates them.
    end = start + 1
    while end < len(lines) and lines[end].strip():
        end += 1

    # And the comment immediately above, if there is one, because that is where the author said
    # what they meant in words.
    head = start
    while head > 0 and lines[head - 1].strip().startswith("\\*"):
        head -= 1
    return [l.rstrip() for l in lines[head:end]]


# ---------------------------------------------------------------------------- mutation
#
# IS THE PROPERTY STRONG ENOUGH? A property that holds tells you the policy satisfies it. It does
# not tell you the property was worth satisfying, and the two are easy to confuse -- `ensures TRUE`
# holds of everything.
#
# The question has a mechanical answer: BREAK THE POLICY AND SEE IF THE PROPERTY NOTICES. Damage it
# in small, meaningful ways -- delete a rule, invert a permit, drop a condition -- and re-check. A
# property that survives every mutant is not constraining the policy; it is describing something
# else, or nothing.
#
# This matters most for a property somebody did not write by hand. A documented failure in agentic
# verification (measured by Lahiri, arXiv:2608.21516) is exactly this: asked to produce both an artifact and its
# specification, a model can find that a trivial specification is the cheapest way to pass. A
# mutation score is the mechanical defence here, because the failure mode is a property that is
# perfectly true.
#
# NOT A COVERAGE METRIC. A surviving mutant is not automatically a gap: a property about trades
# should be untouched by damage to an unrelated rule about approvals, and reporting that as a
# failure would train people to write properties that range over everything. What is damning is
# ALL mutants surviving -- see `mutation_report`.


def mutants(policies: list[dict]) -> list[tuple[str, list[dict]]]:
    """Small, meaningful damage to a policy set: (what was done, the damaged set).

    Three kinds, chosen because each is a mistake somebody actually makes rather than a random
    perturbation -- a rule deleted in a refactor, an effect typed wrong, a condition dropped while
    rewriting one. A property worth having notices at least one of them.

    ORDERED BREADTH FIRST -- every rule's deletion, then every rule's inversion, then the dropped
    conditions -- because the caller takes a PREFIX of this list (`all_mutants[:cap]`) and the
    default cap is 8. Grouped by rule, as this was, a 7-rule policy spent all 8 on rules 1 to 3 and
    NEVER BROKE rules 4 to 7. A property about a later rule then survived every mutant tried and
    was rejected for "not constraining this policy at all" -- which was false, and is the worst
    thing this gate can say, because the whole point of it is to catch a property that constrains
    nothing.

    IT WAS FOUND IN A LIVE SESSION and it is not hypothetical. A property about
    `initiate_transfer` (rules 4 and 5 of `examples/aws2/agent-policy.dw`) caught 0 of the first 8
    mutants and 4 of all 21 -- every one of the four on rules 4 and 5, exactly the rules it was
    about. It cost three drafting attempts and two sessions before the gate, rather than the
    drafts, was suspected.
    """
    deleted: list[tuple[str, list[dict]]] = []
    inverted: list[tuple[str, list[dict]]] = []
    dropped: list[tuple[str, list[dict]]] = []

    for i, rule in enumerate(policies):
        # Deleted. The commonest edit there is, and the one a property most obviously should catch.
        deleted.append((f"rule {i + 1} ({rule['effect']}) deleted",
                        [p for j, p in enumerate(policies) if j != i]))

        # Inverted. A permit typed as a forbid is a one-word mistake with the largest possible
        # consequence, and it is what the AgentCore trust-decay policy turns out to be.
        flipped = "forbid" if rule["effect"] == "permit" else "permit"
        inverted.append((f"rule {i + 1} turned into a {flipped}",
                         [{**p, "effect": flipped} if j == i else p
                          for j, p in enumerate(policies)]))

        # Each condition dropped in turn: the rule now applies more widely than it was written to.
        terms = conjuncts(rule.get("cond"))
        if len(terms) > 1:
            for k in range(len(terms)):
                kept = [t for m, t in enumerate(terms) if m != k]
                dropped.append((
                    f"rule {i + 1} lost a condition: {describe_term(terms[k])}",
                    [{**p, "cond": rebuild(kept)} if j == i else p
                     for j, p in enumerate(policies)]))
        elif terms:
            dropped.append((f"rule {i + 1} lost its only condition",
                            [{**p, "cond": rebuild([])} if j == i else p
                             for j, p in enumerate(policies)]))

    # Deletion first because it is the damage every property should notice, and one per rule before
    # any rule's second mutant -- so the cheapest cap still touches every rule in the policy.
    return deleted + inverted + dropped


def mutation_report(args, policies: list[dict], vocab: dict, keys, held: bool) -> int:
    """Damage the policy repeatedly and report which mutants the property caught.

    `held` is whether the property holds on the policy AS WRITTEN, and it changes what this means:

        held=False   the property already discriminates -- it caught the real policy. Scoring it
                     against damaged ones adds nothing, and is skipped.
        held=True    the interesting case. The property is satisfied; the question is whether it
                     would have been satisfied by anything.
    """
    if not held:
        print("\nNot scored: the property module does not hold on the policy set as written, so it\n"
              "has already shown it can tell one policy set from another. Fix the finding first.")
        return 0

    all_mutants = mutants(policies)
    cap = args.mutants or len(all_mutants)
    tried = all_mutants[:cap]

    print(f"\nMUTATION SCORE -- does this property module notice when the policy set breaks?\n"
          f"  {len(tried)} mutant(s)"
          f"{f' of {len(all_mutants)}, capped by --mutants' if cap < len(all_mutants) else ''}\n")

    caught, survived = 0, []
    with workdir(args, "anchor-mutate-") as work:
        shutil.copyfile(SPECS / "DogwoodSemantics.tla", work / "DogwoodSemantics.tla")
        for n, (what, damaged) in enumerate(tried, 1):
            # A mutant that leaves no rules at all says nothing about the property: every policy
            # question is trivial on an empty set, and counting it either way would be noise.
            if not damaged:
                continue
            (work / "PolicyUnderTest.tla").write_text(
                generate_policy_module(args.policy, damaged, vocab, keys=keys), encoding="utf-8")
            try:
                still, _ = check_property(
                    work, args.property_module,
                    said=f"  TLC {n}/{len(tried)}  mutant: {what}. Does the property module notice?")
            except Unsupported:
                # The damage produced something outside the modelled subset. Not evidence about
                # the property, so it is not counted against it.
                continue

            if still:
                survived.append(what)
            else:
                caught += 1
                print(f"  caught   {what}")

    for what in survived:
        print(f"  MISSED   {what}")

    total = caught + len(survived)
    print(f"\n  {caught} of {total} caught.")

    if total and caught == 0:
        print("\nTHE PROPERTY MODULE CAUGHT NOTHING. It holds of the policy set, and of every broken\n"
              "version of the policy set too -- so it is not constraining this policy set at all. Either it\n"
              "ranges over requests the policy never sees, or it asserts something trivially true.\n"
              "A property module nothing can violate is not a check.")
        # ITS OWN EXIT CODE, not 1. "Your property is broken" and "your property is weak" are
        # opposite findings -- the first says the policy is wrong, the second says the check is --
        # and sharing a code makes a caller read a useless property as a discriminating one.
        return WeakProperty

    print("\nA surviving mutant is not automatically a gap: a claim about one action should be\n"
          "untouched by damage to an unrelated rule. What would be damning is ALL of them\n"
          "surviving, and that is what this is for.")
    return 0


def violated_by(out: str) -> list[str]:
    """The invariants that failed, with the state that broke each.

    ANY state conjunct, not a particular variable name. This read `startswith("req")` -- which is
    what `firewall.tla` happens to call its variable -- so a property module that named its own
    variable anything else reported a violation with NO counterexample beside it, and the one
    value that explains the failure was silently dropped. A counterexample nobody can see is the
    same as not having one.
    """
    lines = out.splitlines()
    found = []
    for i, line in enumerate(lines):
        if "is violated" not in line:
            continue
        # Read to the blank line that ends the state. TWO SHAPES, because TLC prints a
        # multi-variable state as `/\ name = value` conjuncts and a single-variable one as a bare
        # `name = value` -- and a reader that handled only the first showed nothing at all for the
        # commonest property module, which holds one variable still.
        state = []
        for raw in lines[i + 1:i + 12]:
            s = raw.strip()
            if not s:
                break
            s = s.removeprefix("/\\").strip()
            if VARIABLE_LINE.match(s):
                state.append(s)
        found.append(line.split("Error: ")[-1].strip()
                     + "".join(f"\n      {s}" for s in state))
    return found



# ---------------------------------------------------------------------------- describe
KIND_NAMES = {"s": "string", "n": "integer", "b": "boolean", "a": "address"}

# The string `field_domain` appends so that "does not match" is reachable. A NUL byte, chosen so it
# cannot collide with a real value -- which also makes it something no author can type. It is
# DESCRIBED below, never offered as a literal to write.
UNNAMED = "\u0000none"


def writable(domain: list) -> list:
    """The domain without the sentinel."""
    return [(k, v) for k, v in domain if not (k == "s" and v == UNNAMED)]


def constructor(kind: str, value) -> str:
    """One value as a property module must WRITE it. `22` is not a value here; `Num(22)` is."""
    if kind == "b":
        return f'Bool({"TRUE" if value else "FALSE"})'
    if kind == "n":
        return f"Num({value})"
    if kind == "a":
        return f'Addr({", ".join(str(o) for o in value)})'
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'Str("{escaped}")'


def module_name(stem: str) -> str:
    """A policy's file name as a legal TLA+ module name.

    TLA+ identifiers are letters, digits and underscores, and cannot START with a digit -- while a
    policy file is very often named `07-trust-decay.dw`. The skeleton used the stem unchanged, so
    following the workflow on such a file produced a module TLC refuses to parse, with an
    `AbortException` that names neither the cause nor the fix.

    THE MODULE NAME MUST MATCH ITS FILE NAME, so this is also what the property file has to be
    called -- said in the skeleton's header rather than left to be discovered.
    """
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in stem).strip("_")
    return f"P_{cleaned}" if not cleaned or cleaned[0].isdigit() else cleaned


def skeleton(name: str, policy: str, policies: list[dict], vocab: dict) -> str:
    """A property module that compiles and checks something, for the author to edit.

    Deliberately not a stub with holes. A skeleton that does not run teaches nothing about whether
    the harness is wired correctly, and the wiring -- EXTENDS, the INSTANCE, the shape of Decide's
    arguments -- is the part nobody can guess.
    """
    action = sorted(vocab["actions"])[0] if vocab["actions"] else "Act"
    fields = sorted(vocab["input"])

    if fields:
        # Named explicitly rather than drawn from InputDomain: see the warning below. The sentinel
        # is dropped -- it exists to make non-matching reachable inside the model, and an author
        # who wants that here writes a value of their own.
        sets = "\n".join(
            f'{f}Values == {{' + ", ".join(constructor(k, v)
                                           for k, v in writable(vocab["domains"][("input", f)])) + "}"
            for f in fields)
        binds = ", ".join(f"{f} \\in {f}Values" for f in fields)
        rec = ", ".join(f"{f} |-> {f}" for f in fields)
        requests = f"{sets}\n\nRequests == {{[{rec}] : {binds}}}"
        claim = (f"\\* EDIT THIS. It says the policy grants every request named above, which is\n"
                 f"\\* almost certainly not what {name}.dw means.\n"
                 f"EverythingIsGranted == Grants(req)")
    else:
        requests = ('\\* This policy reads no input fields, so one request is the whole space.\n'
                    'Requests == {[f \\in {} |-> Str("")]}')
        claim = "EverythingIsGranted == Grants(req)"

    return f"""---------------------------- MODULE {name} ----------------------------
\\* What {policy}.dw is SUPPOSED to mean, stated by its author. The three built-in findings
\\* (VACUOUS, REDUNDANT/DEAD, diff) are the claims statable WITHOUT knowing intent; this is the
\\* other kind, and only the author can write it.
\\*
\\* SAVE THIS AS {name}.tla -- TLA+ requires the file name to match the module name, and a
\\* module name may not contain `-` or `.` or begin with a digit, so it is not always the policy's
\\* own name.
\\*
\\* Check it with:  python src/checker/properties.py {policy}.dw --property {name}.tla
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

\\* The verdict for one request. No session: "what does this policy decide for this request" is
\\* not a temporal question, so there is no state machine beyond holding one request still.
Grants(input) == D!Decide(<<Request("{action}", input)>>, Policies, 1, AllValues)

(***************************************************************************)
(* THE REQUESTS THIS CLAIM IS ABOUT.                                       *)
(*                                                                         *)
(* Written out rather than derived from InputDomain, and that is the       *)
(* point. A space derived from the policy's own literals cannot test a     *)
(* claim about a value the policy never mentions: delete the rule that     *)
(* names a value and it vanishes from the vocabulary, so the claim ranges  *)
(* over nothing and PASSES having looked at nothing.                       *)
(*                                                                         *)
(* Add the values your claim is about, including ones this policy never    *)
(* mentions.                                                               *)
(***************************************************************************)
{requests}

\\* One request, chosen nondeterministically and held, so a violation's counterexample NAMES the
\\* request that breaks the claim rather than merely reporting that one exists.
VARIABLE req
Init == req \\in Requests
Next == UNCHANGED req
Spec == Init /\\ [][Next]_req

(***************************************************************************)
(* THE CLAIM.                                                              *)
(***************************************************************************)
{claim}

=============================================================================
"""


def describe(args, policies: list[dict], vocab: dict, schema: dict, reading: str) -> int:
    """Everything a property module may name, as JSON, plus a skeleton that already runs."""
    name = module_name(args.policy.stem)

    def side(which):
        out = []
        for f in sorted(vocab[which]):
            domain = vocab["domains"][(which, f)]
            kept = writable(domain)
            out.append({
                "name": f,
                "kind": KIND_NAMES.get(domain[0][0], "unknown"),
                "domain": [constructor(k, v) for k, v in kept],
                # The model admits one more value than the policy names, so that a condition
                # failing to match is reachable. Not writable -- for a string it is a NUL byte --
                # so it is reported rather than offered.
                "plusOneValueThePolicyNeverNames": len(kept) != len(domain),
            })
        return out

    doc = {
        "source": args.policy.name,
        "reading": reading,
        "module": "PolicyUnderTest",
        "actions": sorted(vocab["actions"]),
        "kinds": sorted(vocab["kinds"] | {DECISION_KIND}),
        "decisionKind": DECISION_KIND,
        "inputFields": side("input"),
        "outputFields": side("output"),
        "pinKeys": schema["keys"],
        "rules": [{"index": i, "effect": p["effect"], "actions": p["actions"] or ["(any)"]}
                  for i, p in enumerate(policies, 1)],
        "operators": {
            "Request(action, input)": "one request as the evaluator reads it, at time 1",
            "Ev(action, kind, input, output, time)": "ONE EVENT AT A CHOSEN TIME AND KIND -- what "
                                                     "a claim about a SESSION is built from. "
                                                     "`action` and `kind` are PLAIN strings and "
                                                     "`time` a PLAIN integer -- Ev(\"trade\", "
                                                     "\"request\", NoFields, NoFields, 900), never "
                                                     "Str(\"trade\") or Num(900). Tagging is for "
                                                     "field VALUES inside the input/output records "
                                                     "and nowhere else. `time` is in SECONDS: a "
                                                     "claim about a 15m window needs events 900 "
                                                     "apart, not two",
            "NoFields": "an empty input or output record",
            "D!Decide(trace, Policies, i, AllValues)": "the verdict for event `i` of a trace you "
                                                       "built -- a sequence of Ev(...), in time "
                                                       "order. This is how a TEMPORAL claim is "
                                                       "stated; `Grants` in the skeleton is the "
                                                       "one-event shorthand",
            "Policies": "the rule set, as the sequence Decide evaluates",
            "AllValues": "every value any field may take -- Decide's last argument",
            "InputDomain": "[field |-> {values}] for the fields above",
            "OutputDomain": "[field |-> {values}] for the output fields",
            "PinKeys": "the fields a universal pin partitions on; empty means global-trace",
        },
        "constructors": {
            "Str(x)": "a string",
            "Num(x)": "an integer",
            "Bool(x)": "TRUE or FALSE",
            "Addr(a, b, c, d)": "an address, FOUR OCTETS -- TLC works in Java ints, so "
                                "208.4.4.0 as 3489924096 is not a value it can hold",
            "Anon": "the anonymous principal/resource/session a per-request claim uses",
        },
        "rules_for_writing_one": [
            "EXTENDS PolicyUnderTest, and instantiate DogwoodSemantics with Cases <- << >>.",
            "Scalars are TAGGED. Inside an event's record write Num(22), never 22. Compare with = "
            "and # against a tagged value (s = Str(\"a1\")), but order the number inside "
            "(x.v <= 22): x <= Num(22) fails at run time.",
            "There is no Inputs. State the requests your claim is about, including values this "
            "policy never mentions, or the claim may range over nothing and pass.",
            "Decide the allowed and denied cases from the requirement BEFORE evaluating the "
            "policy. A claim written from the policy's own behaviour restates it.",
            "Include a claim that one specific, fully compliant session is ALLOWED. A module of "
            "refusal claims alone cannot be broken by removing a permission. 'X requires Y' means "
            "'without Y, refused', not 'with Y, always allowed'.",
            "Put every prerequisite event in the session, and each value where the policy reads it: "
            "inputFields in an event's input record, outputFields in its output record.",
            "The .cfg must name SPECIFICATION Spec and every INVARIANT. A claim nobody listed is "
            "a claim nobody checked.",
        ],
        "skeleton": skeleton(name, args.policy.stem, policies, vocab),
        "config": ("SPECIFICATION Spec\n\n"
                   "\\* Naming the claims is deliberate. A claim nobody listed is a claim nobody\n"
                   "\\* checked.\n"
                   "INVARIANT EverythingIsGranted\n"),
    }
    print(json.dumps(doc, indent=2))
    return 0


# ---------------------------------------------------------------------------- entry
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policy", type=Path, help="a .dw policy file")
    ap.add_argument("--against", type=Path, metavar="OTHER.dw",
                    help="a second .dw file -- the version being replaced. Reports whether this "
                         "policy is MORE PERMISSIVE, LESS PERMISSIVE, EQUIVALENT or INCOMPARABLE "
                         "to it, with a witness session for each direction, rather than checking "
                         "each rule")
    ap.add_argument("--attempts", type=int, default=3, help="session length bound (default 3)")
    ap.add_argument("--amount", type=int, default=2,
                    help="numeric domain for input fields, 1..N (default 2)")
    ap.add_argument("--max-fields", type=int, default=4, metavar="N",
                    help="refuse a policy reading more than N input/output fields. The"
                         " request space is the product of their domains, so this bounds"
                         " state space rather than soundness (default 4)")
    ap.add_argument("--property", type=Path, metavar="FILE.tla", dest="property_module",
                    help="a TLA+ module of your own, extending PolicyUnderTest, stating what the "
                         "policy is supposed to mean. Needs a companion .cfg naming its invariants")
    ap.add_argument("--event-schema", type=Path, metavar="FILE.dwschema",
                    help="the .dwschema the policy set is deployed under. Without one, a policy "
                         "binding eventResource or eventPrincipal is read under AgentCore's own "
                         "schema (history per session), and any other under Dogwood's default: "
                         "callerPrincipal pinned, so a temporal condition sees only the requesting "
                         "principal's earlier events. Pass the real schema if you have one, or "
                         "--unpinned if yours has no universal pin")
    ap.add_argument("--verbose", action="store_true", help="print the TLC output for each permit")
    ap.add_argument("--json", action="store_true",
                    help="emit the result as JSON, including the witness SESSION as structured "
                         "events rather than a one-line summary. For an agent, or anything else "
                         "that has to act on the answer instead of read it")
    ap.add_argument("--mutation-score", action="store_true",
                    help="after a --property check that HOLDS, break the policy in small ways and "
                         "report which breakages the property module notices. A module that survives "
                         "every one of them is not constraining this policy set -- it holds, and it "
                         "would hold of anything")
    ap.add_argument("--mutants", type=int, default=None, metavar="N",
                    help="cap the number of mutants tried (default: all of them)")
    ap.add_argument("--no-blame", action="store_true",
                    help="skip working out WHICH condition term makes an inert rule inert. That "
                         "search costs one extra TLC run per term of each inert rule, and it is "
                         "the difference between a verdict and an instruction")
    ap.add_argument("--keep", type=Path, metavar="DIR",
                    help="write the generated TLA+ module, its .cfg and the raw TLC output here "
                         "instead of discarding them. What a reader who knows TLA+ needs in order "
                         "to disagree: the model as checked, and the command to re-run it")
    ap.add_argument("--smoke", type=int, metavar="N", nargs="?", const=1000,
                    help="run TLC as a random walk of N behaviours (default 1000) instead of "
                         "exhaustively. Reports `live` -- which is SOUND, a witness is a witness "
                         "however it was found -- or `unknown`. It can never report VACUOUS, "
                         "REDUNDANT or DEAD: those are claims of absence, and a random walk cannot "
                         "establish absence. For models too big to exhaust")
    ap.add_argument("--explain", action="store_true",
                    help="before checking a --property, say in English what each of its claims "
                         "FORBIDS, which states it will be checked in, and which of those its "
                         "condition even applies to. The one step in this pipeline nothing else "
                         "verifies is whether the property module says what you meant, and this is the "
                         "sentence to disagree with while disagreeing is still cheap")
    ap.add_argument("--eval", type=str, default=None, metavar="EXPR",
                    help="evaluate a TLA+ expression in this policy's own semantics and print the "
                         "value. With --property, the module's definitions are in scope too, so "
                         "`Session(960)` or `TradeAllowed(960)` can be asked directly. Seconds, and "
                         "it checks nothing -- it answers what a value IS, which is the question "
                         "you otherwise have to write an invariant and run a check to find out")
    ap.add_argument("--pinned", action="store_true",
                    help="Dogwood's own default reading, and Anchor's, stated explicitly: "
                         "callerPrincipal pinned on every event kind, so a temporal predicate sees "
                         "only its own principal's events")
    ap.add_argument("--unpinned", action="store_true",
                    help="check under global-trace semantics: no pins, so a temporal predicate "
                         "sees every principal's events in the session. For a deployment whose "
                         "event schema has no universal pin")
    ap.add_argument("--decision-probe", action="store_true",
                    help="with --property: ask whether the policy's answer VARIES over the states "
                         "this module ranges over, and stop. Two TLC runs, seconds. A property module "
                         "whose policy set refuses everything it names holds without testing "
                         "anything, and mutation scoring can only report that afterwards, as a "
                         "symptom. Exit 4 when the decision is constant")
    ap.add_argument("--parse", action="store_true",
                    help="with --property: check that the module COMPILES against this policy's "
                         "generated vocabulary, and stop. SANY only, no TLC -- about a second "
                         "rather than minutes. The commonest thing wrong with a freshly written "
                         "property module is that it does not compile, and finding that out from "
                         "a model-checking run means paying for the run first")
    ap.add_argument("--syntax", action="store_true",
                    help="before checking anything, put the policy to the reference implementation "
                         "(`dogwood check-parse`) and stop if it will not parse. A syntax error is "
                         "not a verification finding, but it is the reason a run produces none -- "
                         "and this says so in the engine's words, pointing at the token, instead "
                         "of arriving later as a refusal that reads like a limit of this tool. "
                         "Costs about 35ms; skipped with a note when the binary is not built")
    ap.add_argument("--witness", action="store_true",
                    help="when a --property claim is BROKEN, carry the counterexample back into "
                         "Dogwood: the concrete session it stands for, as a .log trace, and the "
                         "verdict `dogwood replay` gives it. The counterexample is a TLA+ variable; "
                         "this is the same finding in the language the policy was written in, "
                         "confirmed by the reference engine rather than by our model")
    ap.add_argument("--describe", action="store_true",
                    help="print, as JSON, what a --property module extending PolicyUnderTest may "
                         "name for this policy -- actions, fields, domains, constructors -- plus a "
                         "skeleton module that already runs. Checks nothing")
    args = ap.parse_args()

    # ONE READING PER RUN. --event-schema, --pinned and --unpinned are three answers to the same
    # question, and taking the first one given while ignoring the rest -- which is what happened
    # -- reports a verdict under a reading the caller did not ask for, without saying so.
    chosen = [flag for flag, given in (("--event-schema", args.event_schema is not None),
                                       ("--pinned", args.pinned), ("--unpinned", args.unpinned))
              if given]
    if len(chosen) > 1:
        ap.error(f"{' and '.join(chosen)} each choose the event-schema reading; pass one")

    for f in (args.policy, args.against):
        if f is not None and not f.exists():
            print(f"no such policy file: {f}", file=sys.stderr)
            return 2

    # BEFORE OUR OWN PARSER, when asked. The reference implementation is the authority on whether
    # a file is Dogwood at all, and a syntax error found here is reported as one rather than
    # arriving later dressed as a limit of the modelled subset.
    if args.syntax:
        from checker.engine import BUILD_IT, check_parse       # noqa: PLC0415

        for f in (args.policy, args.against):
            if f is None:
                continue
            result = check_parse(f)
            if not result["ran"]:
                print(f"syntax check skipped: {result['output']}", file=sys.stderr)
                break
            if not result["ok"]:
                print(f"SYNTAX ERROR in {f.name} -- the reference implementation will not parse "
                      f"it.\nNothing below was checked.\n", file=sys.stderr)
                print(result["output"], file=sys.stderr)
                # 2, the no-verdict code. A policy that does not parse has not been checked, and
                # a 0 here would be a clean bill of health for a file nobody could read.
                return 2
            print(f"{f.name}: parses, per the reference implementation", file=sys.stderr)

    policy_text = args.policy.read_text(encoding="utf-8")
    other_text = args.against.read_text(encoding="utf-8") if args.against else ""

    # A policy written for AgentCore -- binding `eventResource` / `eventPrincipal` -- is read under
    # AgentCore's event schema unless the caller chose a reading. Under Dogwood's default those
    # fields do not exist, so the only alternative to this is refusing the policy.
    agentcore_auto = (not chosen
                      and (uses_agentcore_fields(policy_text) or uses_agentcore_fields(other_text)))
    schema_file = AGENTCORE_SCHEMA if agentcore_auto else args.event_schema
    # Recorded as the reading from here on, so everything handed the schema later -- the witness
    # replay above all -- uses the one the verdicts were reached under.
    args.event_schema = schema_file

    try:
        # The event schema, which decides what the policy MEANS before anything is checked about
        # what it says -- read first, because it also says what the policy's scope fields are
        # called, and how far back a window may look. Both halves of a schema are different jobs:
        # a partial pin becomes an ordinary conjunct, a universal one a partition key stamped onto
        # every term.
        # WITHOUT A SCHEMA, DOGWOOD'S OWN DEFAULT: callerPrincipal pinned. That is the reading of a
        # policy set deployed on Dogwood with no schema of its own -- not on AgentCore, which has
        # its own -- so it is what an unconfigured check answers about; `--unpinned` opts out.
        # Both are built as the dict rather than read from Dogwood's shipped files, so neither
        # needs a file or the submodule; the values are what `parse_schema` returns for
        # `configuration/event-schemas/{pinned,unpinned}.dwschema`, which
        # tests/strands/event_schema_readings.py checks.
        if schema_file is not None:
            schema = parse_schema(schema_file.read_text(encoding="utf-8"))
        else:
            schema = {"keys": [] if args.unpinned else ["principal"], "partial": {}, "paths": {},
                      "max_window": DEFAULT_MAX_WINDOW, "scope_fields": dict(DEFAULT_SCOPE_FIELDS)}

        # A policy looking back further than the deployment allows is a validation error, so
        # answering questions about it would be answering about something undeployable.
        cap = schema["max_window"]
        policies = parse_policies(policy_text, "", cap, schema["scope_fields"])
        other = (parse_policies(other_text, "", cap, schema["scope_fields"])
                 if args.against else None)

        agentcore_warnings = []
        if is_agentcore(schema):
            for rules, f in ((policies, args.policy), (other, args.against)):
                if rules is None:
                    continue
                refuse_unsound(rules)
                rejected, warned = rejections(rules)
                agentcore_warnings += [f"{f.name}: {w}" for w in warned]
                if rejected:
                    # Not REFUSED: Anchor could model this. AgentCore would not create it, so there
                    # is no deployed policy for a verdict to be about. Same exit as no verdict.
                    print(f"REJECTED BY AGENTCORE: {f.name} could not be created as written, so "
                          f"nothing was checked\n  " + "\n  ".join(rejected), file=sys.stderr)
                    return 2

        for rules in (policies, other):
            if rules is not None:
                apply_pins(rules, schema)
                if schema["keys"]:
                    stamp_keys(rules, schema["keys"])
        # The vocabulary must span BOTH files. A version that adds a permit for an action the
        # other never mentions would otherwise never have that action attempted, and the run
        # would report "no difference" having not looked -- the one wrong answer that matters.
        vocab = vocabulary(policies + (other or []), args.amount, args.max_fields)
    except Unsupported as e:
        # The house rule: refuse rather than approximate. A translator that quietly mishandles a
        # construct produces a verdict nobody can attribute.
        print(f"REFUSED: {args.policy.name} is outside the modelled subset\n  {e}", file=sys.stderr)

        # AND, FREE ON THIS PATH ONLY, the question our own message cannot answer: is the thing we
        # would not model a construct at all? Our parser reads a subset, so it has two ways to
        # fail and one message for both -- "outside the subset" and "this file is broken" need
        # opposite responses. 35ms, spent only once a run has already failed.
        from checker.engine import explain_refusal              # noqa: PLC0415

        if extra := explain_refusal(args.policy):
            print(extra, file=sys.stderr)
        return 2

    # Say which reading produced the answers. Leaving it implicit is how a verdict computed under
    # one reading gets read as one about another deployment.
    where = schema_file.name if schema_file is not None else (
        "--unpinned" if args.unpinned else "--pinned")
    if agentcore_auto:
        reading = ("the policy binds eventResource/eventPrincipal, so every answer below uses\n"
                   "  AgentCore's event schema: history partitioned by session, and one gateway\n"
                   "  in the model -- a rule scoped to it applies to every request. Not modelled:\n"
                   "  a response is assumed recorded before the next request, where AgentCore\n"
                   "  records it \"shortly after\" (docs/agentcore.md, question 4).")
    elif args.event_schema is None and not args.pinned and not args.unpinned:
        # The default, said as a default: the reader may not know one was chosen for them, or
        # that their deployment may use another.
        reading = ("no --event-schema given, so every answer below uses Dogwood's own default\n"
                   "  reading: callerPrincipal pinned on every kind, so a temporal condition sees\n"
                   "  only the requesting principal's events. Pass --event-schema for your\n"
                   "  deployment's real one, or --unpinned if it has no universal pin.")
    elif schema["keys"]:
        reading = (f"under {where}: partitioned by "
                   f"{', '.join(schema['keys'])} -- a temporal predicate sees only its own partition")
    else:
        reading = f"under {where}: no universal pin, so global-trace semantics"

    # Before the preamble is printed, because the description is JSON and a prose line above it
    # would make the whole document unparseable.
    if args.describe:
        return describe(args, policies, vocab, schema, reading)

    if not args.json:
        print(reading + "\n")
        for w in agentcore_warnings:
            print(f"AgentCore may reject: {w}\n")

    if args.property_module is not None:
        return prove(args, policies, vocab, schema["keys"])

    # `--eval` with no property module: the policy's own generated vocabulary is the context, which
    # is what "what is this field's domain" and "what does `Policies` look like" are asked against.
    # No variables there, so no spec is needed -- and TLC would refuse an empty config if there were.
    if args.eval:
        with workdir(args, "anchor-eval-") as work:
            (work / "PolicyUnderTest.tla").write_text(
                generate_policy_module(args.policy, policies, vocab, keys=schema["keys"]),
                encoding="utf-8")
            shutil.copyfile(SPECS / "DogwoodSemantics.tla", work / "DogwoodSemantics.tla")

            ok, out = run_eval(args.eval, "PolicyUnderTest", work, spec=None)
            print(f"  {args.eval}\n")
            print("\n".join(f"      {line}" for line in out.splitlines()[:60]))
            if not ok:
                print("\nThe expression did not evaluate. TLC's output is above.")
            return 0 if ok else 2

    if args.against is not None:
        return compare(args, policies, other, vocab, schema["keys"], reading)

    permits = [i + 1 for i, p in enumerate(policies) if p["effect"] == "permit"]
    forbids = [i + 1 for i, p in enumerate(policies) if p["effect"] == "forbid"]

    tier = (f", SMOKE: {args.smoke} random sessions, not exhaustive"
            if args.smoke else "")
    if not args.json:
        print(f"{args.policy.name}: {len(permits)} permit(s), {len(forbids)} forbid(s), "
              f"bound {args.attempts} attempts{tier}\n")

    if not policies:
        print("nothing to check -- the file declares no rules")
        return 0

    findings = []
    detail: list[dict] = []
    runs: list[tuple[str, str]] = []
    with workdir(args, "anchor-vacuity-") as work:
        (work / "PolicyUnderTest.tla").write_text(
            generate_policy_module(args.policy, policies, vocab, keys=schema["keys"]), encoding="utf-8")
        for module in ("Vacuity.tla", "DogwoodSemantics.tla"):
            shutil.copyfile(SPECS / module, work / module)

        # Counted up front so each progress line can say how far along it is: two runs for a
        # permit, whose sharper question is asked too, and one for a forbid.
        total = sum(2 if r["effect"] == "permit" else 1 for r in policies)
        done = 0
        for i, rule in enumerate(policies, 1):
            shown = " | ".join(rule["actions"]) or "(any)"
            label = f'{rule["effect"]} #{i}  action == {shown}'

            # Does deleting this rule change any verdict? One question, both shapes: a forbid
            # that never denies, and a permit some other permit always covers.
            done += 1
            progress(f"  TLC {done}/{total}  {rule['effect']} #{i}: does deleting it change any verdict?")
            matters, out = check_one(work, i, args.attempts, args.amount, "NeverMatters",
                                     smoke=args.smoke)
            # One config and one output PER RULE, because each run sets a different `Target`.
            # A single kept pair would describe whichever rule happened to be checked last.
            keep_run(args, work, f"rule-{i}-NeverMatters", out)
            runs.append((f"rule-{i}-NeverMatters", "Vacuity"))

            # For a permit, ask the sharper question too. Vacuous implies redundant, so a
            # permit reported vacuous is also deletable -- but "never fires at all" is a more
            # useful thing to be told than "something else covers it".
            fires = None
            if rule["effect"] == "permit":
                done += 1
                progress(f"  TLC {done}/{total}  permit #{i}: can it grant anything at all?")
                fires, fout = check_one(work, i, args.attempts, args.amount, "NeverFires",
                                        smoke=args.smoke)
                keep_run(args, work, f"rule-{i}-NeverFires", fout)
                runs.append((f"rule-{i}-NeverFires", "Vacuity"))
                if fires:
                    out = fout

            # `None` only ever arrives from a smoke run, and only the absence claims are
            # blocked by it: a witness found by a random walk settles `live` for good.
            if matters:
                verdict, note = "live", f"witness: {witness(out)}"
            elif rule["effect"] == "permit" and fires is None:
                verdict, note = "unknown", f"no witness in {args.smoke} random sessions -- not a verdict"
            elif rule["effect"] == "permit" and not fires:
                verdict, note = "VACUOUS", f"no session of up to {args.attempts} attempts makes it grant"
            elif matters is None:
                verdict, note = "unknown", f"no witness in {args.smoke} random sessions -- not a verdict"
            elif not matters:
                verdict = "REDUNDANT" if rule["effect"] == "permit" else "DEAD"
                note = "deleting it changes no verdict in any session"

            # Only for a rule already found inert, and never under --smoke: minimising against
            # `unknown` would be minimising against the absence of an answer.
            why, culprits = ("", [])
            if verdict in ("VACUOUS", "REDUNDANT", "DEAD") and not args.smoke and not args.no_blame:
                why, culprits = blame(work, policies, vocab, schema["keys"], i, verdict, args)

            story = narrate(witness_events(out)) if verdict == "live" else []
            detail.append({
                "index": i,
                "effect": rule["effect"],
                "actions": rule["actions"] or ["(any)"],
                "verdict": verdict,
                "note": note,
                # Only a live rule has a witness: the other verdicts are claims of ABSENCE, and
                # there is no session to show for "this never happens".
                "witness": witness(out) if verdict == "live" else None,
                "session": witness_events(out) if verdict == "live" else [],
                "narrative": story,
                # Why it is inert: "structural" (the condition is not the reason), "terms" (these
                # are), or "" when the search was not run. Absent reasons are not guessed at.
                "blame": {"kind": why, "terms": culprits} if why else None,
            })
            findings.append((i, rule["effect"], verdict))

            if args.json:
                continue

            print(f"  {label:34} {verdict:10}{note}")

            # Only for `live`, and only when the session says more than its one-line summary --
            # a policy reading no input fields narrates to the action names already on the line
            # above, and repeating them would be noise per rule rather than detail.
            if verdict == "live" and any("(" in line and "()" not in line for line in story):
                for line in story:
                    print(f"      {line}")

            if why == "terms":
                print(f"      because: {' && '.join(culprits)}")
            elif why == "structural":
                print("      the condition is not why -- it is inert even with no condition at all")

            if args.verbose:
                print("\n".join(f"      {line}" for line in out.splitlines()))

        keep_readme(args, work, runs)

    if args.json:
        print(json.dumps({
            "policy": args.policy.name,
            "reading": " ".join(reading.split()),
            "bound": {"attempts": args.attempts, "amount": args.amount,
                      "exhaustive": not args.smoke,
                      "randomSessions": args.smoke or None},
            "rules": detail,
            # Pre-computed because every consumer wants them and deriving them means knowing
            # which verdicts are claims of absence -- the distinction this project exists to keep.
            "defects": [r["index"] for r in detail
                        if r["verdict"] in ("VACUOUS", "REDUNDANT", "DEAD")],
            "unknown": [r["index"] for r in detail if r["verdict"] == "unknown"],
            "artifacts": str(args.keep) if args.keep else None,
        }, indent=2))
        return 0

    if args.keep:
        print(f"\nartifacts: {args.keep}")

    print()

    # `unknown` is NOT a finding, and must not be summarised as one. Advice to delete a rule we
    # merely did not search hard enough for is the one wrong answer that matters here.
    unknown = [(i, e, v) for i, e, v in findings if v == "unknown"]
    if unknown:
        for i, effect, _ in unknown:
            print(f"unknown {effect} #{i}")
        print()
        print(f"A random walk of {args.smoke} sessions found no witness for these. That is NOT a")
        print("finding: it does not mean the rule is inert, only that this search did not reach a")
        print("session where it matters. Re-run without --smoke to get a verdict, or raise --smoke")
        print("to search further.\n")

    dead = [(i, e, v) for i, e, v in findings if v not in ("live", "unknown")]
    if dead:
        for i, effect, verdict in dead:
            print(f"{verdict} {effect} #{i}")
        print()
        print("A rule that changes no verdict can be deleted, and a policy set is easier to reason")
        print("about the fewer of them it has.")

        # Only the verdicts actually reported. Explaining one that did not occur is noise, and it
        # also makes the output awkward to assert on.
        seen = {v for _, _, v in dead}
        legend = {
            "VACUOUS": ("  VACUOUS    the permit never fires at all -- whatever it was meant to\n"
                        "             allow is unreachable, a bug rather than untidiness"),
            "REDUNDANT": "  REDUNDANT  it fires, but another permit always would too",
            "DEAD": "  DEAD       the forbid never denies anything the rest of the set would allow",
        }
        for verdict in ("VACUOUS", "REDUNDANT", "DEAD"):
            if verdict in seen:
                print(legend[verdict])
    elif not unknown:
        print(f"every rule is load-bearing within {args.attempts} attempts.\n"
              "That is not a proof of correctness -- only that none of them is inert.")

    # Vacuity is a finding, not an error. The exit code says whether the run ANSWERED.
    return 0


if __name__ == "__main__":
    sys.exit(main())
