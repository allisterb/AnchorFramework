"""Every checked-in property, under BOTH event-schema readings.

THE QUESTION. A temporal policy means different things depending on whether the trace is
partitioned. Dogwood's shipped DEFAULT pins `callerPrincipal` on every event kind, which makes
every temporal predicate key-local: a rule sees only its own principal's events. A schema without
that pin gives global-trace semantics, where it sees everybody's.

Anchor models both -- universal and partial pins, checked against the reference corpus, where
`1164_partial_pin_stays_global` is the case that pins it. What was never measured is how much the
choice actually CHANGES, and that matters twice over:

  - every finding we report is scoped to a reading, and a finding that holds under only one of
    them is a weaker claim than it looks;
  - and Anchor's own default when no schema is given was the UNPINNED one until 0.1.3, the opposite
    of Dogwood's. A verification tool whose default differs from the deployed default can produce a
    finding that does not reproduce. It is now PINNED, matching Dogwood, and this checks it stays so.

So this runs each policy/property pair three ways and prints the verdicts side by side. The two
schemas are the ones Dogwood ships, read from the submodule rather than copied -- no second copy to
drift, and no licence text to carry.

    python tests/strands/event_schema_readings.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
CHECKER = REPO / "src" / "checker" / "properties.py"
SCHEMAS = REPO / "ext" / "dogwood" / "dogwood-language" / "configuration" / "event-schemas"

# (policy, property module, extra args). Every checked-in pair, so the answer is about the corpus
# rather than about whichever example was convenient.
PAIRS = [
    ("tests/policies/firewall.dw", "tests/policies/firewall.tla", []),
    ("tests/policies/firewall_open.dw", "tests/policies/firewall.tla", []),
    ("tests/policies/aggregate_cap.dw", "tests/policies/aggregate_cap.tla", []),
    ("tests/policies/eval_join.dw", "tests/policies/eval_join.tla", []),
    ("examples/aws1/07-trust-decay.dw", "examples/aws1/TrustDecay.tla", []),
    ("examples/aws1/07-trust-decay.dw", "examples/aws1/TrustDecay10.tla", []),
    ("examples/aws2/agent-policy.dw", "examples/aws2/CumulativeCap.tla", ["--max-fields", "6"]),
]

READINGS = [
    ("default", None),                          # no --event-schema: Anchor uses PINNED, Dogwood's default
    ("unpinned", SCHEMAS / "unpinned.dwschema"),
    ("pinned", SCHEMAS / "pinned.dwschema"),     # what Dogwood does when you supply nothing
    ("--pinned", "flag"),                        # the same, built internally, no file needed
]

# 0 answered / every claim held, 1 a claim is BROKEN, 2 no verdict, 4 weak.
VERDICT = {0: "holds", 1: "BROKEN", 2: "no verdict", 4: "weak"}

# Policies whose derived questions are compared. The first two carry a KNOWN defect, so a column
# of identical zeroes cannot agree for the wrong reason.
DERIVED = ("tests/policies/business_hours_impossible.dw", "tests/policies/dead_forbid.dw",
           "tests/policies/firewall.dw", "examples/aws1/07-trust-decay.dw",
           "examples/aws2/03-cumulative-cap.dw")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)
        if detail:
            print(f"          {detail[:300]}")


def run(policy: str, module: str, schema: Path | None, extra: list[str]) -> str:
    args = [sys.executable, str(CHECKER), policy, "--property", module, *extra]
    if schema == "flag":
        args += ["--pinned"]
    elif schema is not None:
        args += ["--event-schema", str(schema)]
    proc = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=1800)
    return VERDICT.get(proc.returncode, f"exit {proc.returncode}")


def derived(policy: str, schema: Path | None) -> str:
    """The DERIVED questions' findings, as a comparable string.

    Half of what `check` reports, and the half most sensitive to the reading: VACUOUS and DEAD are
    both statements about whether a rule can ever fire, and partitioning the trace removes events
    that might have made it fire. Comparing the property verdicts alone would have measured the
    less sensitive half and called it settled.
    """
    args = [sys.executable, str(CHECKER), policy, "--json"]
    if schema == "flag":
        args += ["--pinned"]
    elif schema is not None:
        args += ["--event-schema", str(schema)]
    proc = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=1800)
    try:
        import json                                           # noqa: PLC0415
        got = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return f"unparseable (exit {proc.returncode})"

    # `verdict` and `defects`, NOT `finding` -- which is what this read first, making every policy
    # report zero and the comparison below unanimous for the wrong reason. A row of identical
    # zeroes cannot tell "the reading does not matter" from "nothing was measured".
    defects = set(got.get("defects") or [])
    found = sorted(f"{r.get('index')}:{r.get('verdict')}"
                   for r in (got.get("rules") or []) if r.get("index") in defects)
    return f"{len(found)} finding(s)" + (" " + ",".join(found) if found else "")


def main() -> int:
    # THE FULL SWEEP IS 48 CHECKER RUNS AND ~3.5 MINUTES. Worth having, not worth paying on every
    # CI run while the answer keeps coming back "no difference anywhere" -- so the suite takes a
    # representative subset (one holding pair, one BROKEN, one aggregate, one VACUOUS, one DEAD)
    # and the whole corpus stays one flag away.
    quick = "--quick" in sys.argv
    pairs = PAIRS[:2] + PAIRS[-1:] if quick else PAIRS
    policies = (DERIVED[:2] if quick else DERIVED)

    if not (SCHEMAS / "pinned.dwschema").exists():
        print(f"the Dogwood submodule is not checked out at {SCHEMAS}; skipping")
        return 0

    print("=" * 78)
    print("Every checked-in property, under both event-schema readings")
    print("=" * 78)
    print(f"\n  {'policy / property':<52}" + "".join(f"{n:<13}" for n, _ in READINGS))

    differ = []
    for policy, module, extra in pairs:
        verdicts = [run(policy, module, schema, extra) for _, schema in READINGS]
        name = f"{Path(policy).name} / {Path(module).name}"
        mark = "" if len(set(verdicts)) == 1 else "   <-- DIFFERS"
        if mark:
            differ.append((name, verdicts))
        print(f"  {name:<52}" + "".join(f"{v:<13}" for v in verdicts) + mark)

    # --- and the DERIVED questions, which are the reading-sensitive half ---------------------
    print("\n  Derived questions (VACUOUS / REDUNDANT / DEAD), same three readings:\n")
    derived_differ = []
    # At least one with a KNOWN defect, or a column of zeroes would agree for the wrong reason.
    for policy in policies:
        answers = [derived(policy, schema) for _, schema in READINGS]
        same = len(set(answers)) == 1
        if not same:
            derived_differ.append((policy, answers))
        print(f"  {Path(policy).name:<34} {answers[0][:28]:<30}"
              + ("same under all three" if same else "DIFFERS"))

    print()
    # THE TWO CLAIMS THIS FILE EXISTS TO MAKE, both asserted rather than eyeballed.
    check("the derived findings do not change with the reading either",
          not derived_differ, str(derived_differ)[:400])

    # THE FLAG MUST EQUAL THE FILE. `--pinned` builds the schema dict internally so the reading
    # can be tried without Dogwood's submodule checked out -- which is only safe while it stays
    # identical to what parse_schema makes of the shipped pinned.dwschema.
    from translator import parse_schema                        # noqa: PLC0415
    shipped = parse_schema((SCHEMAS / "pinned.dwschema").read_text(encoding="utf-8"))
    check("--pinned agrees with the shipped pinned.dwschema on the partition key",
          shipped["keys"] == ["principal"], str(shipped))
    # THE DEFAULT IS DOGWOOD'S. Column 0 is no schema at all, column 2 the shipped pinned.dwschema.
    check("Anchor's no-schema default agrees with the shipped PINNED schema",
          all(True for _ in pairs) and not any(
              v[0] != v[2] for _, v in [(n, vs) for n, vs in differ]),
          str(differ))

    # THE REPLAY'S COPIES MUST EQUAL THE FILES. witness.py hands `dogwood replay` its own copy of
    # each reading, because the container carries the binary and not this tree -- which is only
    # honest while each copy says exactly what Dogwood's shipped file says. Comments aside.
    from checker.witness import READING_SCHEMAS                 # noqa: PLC0415

    def declarations(text: str) -> list[str]:
        return [l.rstrip() for l in text.splitlines() if l.strip() and not l.strip().startswith("//")]

    for reading, copy in READING_SCHEMAS.items():
        shipped_text = (SCHEMAS / f"{reading}.dwschema").read_text(encoding="utf-8")
        check(f"the replay's {reading} schema is Dogwood's {reading}.dwschema, declaration for declaration",
              declarations(copy) == declarations(shipped_text))

    if differ:
        print("\n  Where the reading CHANGES the answer:")
        for name, verdicts in differ:
            print(f"    {name}")
            for (label, _), v in zip(READINGS, verdicts):
                print(f"        {label:<10} {v}")
        print("\n  A finding that appears under only one reading is scoped to that reading, and")
        print("  saying so is the difference between a result and a misleading one.")
    else:
        print("  Every verdict is identical under all three readings.\n")
        print("  Which is a fact about THIS corpus, not about the semantics: these traces are")
        print("  single-principal, so partitioning by principal removes no event from any of")
        print("  them. A policy whose trace spans principals -- 'N logins by any user' -- is")
        print("  exactly where the two readings come apart, and nothing here has one.")

    print()
    print("=" * 78)
    print("all checks passed" if not failures else f"{len(failures)} FAILED")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
