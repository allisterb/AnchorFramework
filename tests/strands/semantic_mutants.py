"""Hand-written, plausible bugs in aws2's policy set, against the property modules drafted for it.

OPT-IN. `run.py` skips this unless named (`python tests/strands/run.py semantic`), no C# test runs
it, and CI never does. Run it after changing how property modules are drafted or checked.

    python tests/strands/semantic_mutants.py                        examples/aws2/anchor
    python tests/strands/semantic_mutants.py DIR                    modules drafted elsewhere

NO MODEL CALL. Every verdict is SANY and TLC through `src/checker/properties.py`; a few minutes.

WHY BOTH THIS AND `--mutation-score`. The pipeline's mutants are structural -- a rule deleted, a
permit turned into a forbid, a condition dropped -- and a drafted module only has to catch ONE to be
kept. These are the bugs a person writes: a window or a threshold off by a step, a binding to the
account or charge left out. On the 2026-10-04 sweep every module was kept, and these caught 11 of
17. The misses are informative in a way "kept" is not:

  - a module whose one ALLOWED claim names an easy session far from the edge cannot notice a
    policy grown too strict;
  - values taken from the policy's own literals ({499, 500, 2500, 2501}) never try $501-$1000;
  - a refusal claim can be held up by a DIFFERENT rule -- `OverMaxAmountRefused` is refused by
    supervisor approval, never reaching the $2,500 cap.

IT MEASURES THE DRAFTS, NOT THE CODE, so a low score is not a failure: another sweep could score
9 or 14 with nothing broken. It fails only on its own errors -- a module missing, a module that
does not hold on the policy as written, a bug whose text no longer occurs exactly once in the
policy, or a verdict it cannot read. Those mean the numbers below would be meaningless.

THE MODULES ARE READ FROM WHERE A SWEEP WRITES THEM, which is the countdown `drafting_tools.py`
warns about for fixtures. Here it is the point: this scores whichever drafts are there.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = [sys.executable, str(REPO / "src" / "checker" / "properties.py")]
POLICY = REPO / "examples" / "aws2" / "agent-policy.dw"

# (requirement directory, module) -> [(what the bug does, text in agent-policy.dw, replacement)].
# "lax" lets through what the requirement forbids; "strict" refuses what it allows.
MUTANTS: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {
    ("business-hours", "BusinessHours"): [
        ("closes at 18h, not 17h", "lax", 'duration("17h")', 'duration("18h")'),
        ("opens at 8h, not 9h", "lax", 'duration("9h")', 'duration("8h")'),
        ("amount cap 3000, not 2500", "lax",
         "context.input.amount <= 2500", "context.input.amount <= 3000"),
    ],
    ("identity-verification", "IdentityVerification"): [
        ("window 30m, not 15m", "lax", "formerly within 15m", "formerly within 30m"),
        ("any account's verification counts", "lax",
         "input.account:   context.input.account,\n        output.verified: true",
         "output.verified: true"),
        ("a failed verification counts", "lax",
         "input.account:   context.input.account,\n        output.verified: true",
         "input.account:   context.input.account"),
    ],
    ("cumulative-cap", "CumulativeCap"): [
        ("window 24h, not 12h", "strict", "formerly within 12h", "formerly within 24h"),
        ("cap 60000, not 50000", "lax", "total > 50000", "total > 60000"),
        ("cap 40000, not 50000", "strict", "total > 50000", "total > 40000"),
    ],
    ("refund-rate-limit", "RefundRateLimit"): [
        ("allows 4, not 3", "lax", "n > 3", "n > 4"),
        ("allows 2, not 3", "strict", "n > 3", "n > 2"),
        ("window 2h, not 1h", "strict", "formerly within 1h", "formerly within 2h"),
        ("counts every account's refunds", "strict",
         "::request{ input.account: context.input.account } && tp(t)", "::request{ } && tp(t)"),
    ],
    ("supervisor-approval", "SupervisorApproval"): [
        ("threshold 1000, not 500", "lax",
         "context.input.amount > 500", "context.input.amount > 1000"),
        ("window 60m, not 30m", "lax", "formerly within 30m", "formerly within 60m"),
        ("any charge's approval counts", "lax",
         "input.charge_id: context.input.charge_id,\n        output.approved: true",
         "output.approved: true"),
        ("a denied approval counts", "lax",
         "input.charge_id: context.input.charge_id,\n        output.approved: true",
         "input.charge_id: context.input.charge_id"),
    ],
}


def verdict(policy: Path, module: Path) -> tuple[str, str]:
    """("holds" | "violated" | "unread", detail), from the checker's own words."""
    p = subprocess.run(CHECKER + [str(policy), "--property", str(module), "--max-fields", "8"],
                       capture_output=True, text=True, cwd=REPO, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    broken = sorted({line.split("Invariant", 1)[1].split()[0]
                     for line in out.splitlines() if "is violated" in line})
    if broken:
        return "violated", ", ".join(broken)
    if "every claim holds" in out:
        return "holds", ""
    return "unread", " | ".join(out.strip().splitlines()[-3:])[:300]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("modules", nargs="?", type=Path, default=REPO / "examples" / "aws2" / "anchor",
                   help="directory holding <requirement>/<Module>.tla (default: examples/aws2/anchor)")
    p.add_argument("--workers", type=int, default=4, help="TLC runs at once (default: 4)")
    args = p.parse_args()

    if not args.modules.is_dir():
        print(f"SKIPPED: no drafted modules at {args.modules}; run the aws2 sweep first")
        return 0

    errors: list[str] = []
    source = POLICY.read_text(encoding="utf-8").replace("\r\n", "\n")
    modules = {req: args.modules / req / f"{name}.tla" for req, name in MUTANTS}
    for req, module in modules.items():
        if not module.exists():
            errors.append(f"{req}: no module at {module}")
    for (req, _), bugs in MUTANTS.items():
        for label, _, old, _ in bugs:
            if source.count(old) != 1:
                errors.append(f"{req} / {label}: its text occurs {source.count(old)} times in "
                              f"{POLICY.name}, not once")
    if errors:
        print("\n".join(f"  ERROR  {e}" for e in errors))
        return 1

    with tempfile.TemporaryDirectory(prefix="anchor-semantic-") as tmp:
        # One directory per bug, so the checker's runs never share a file.
        jobs = [(req, "the policy as written", "", POLICY) for req, _ in MUTANTS]
        for i, ((req, _), bugs) in enumerate(MUTANTS.items()):
            for j, (label, kind, old, new) in enumerate(bugs):
                bad = Path(tmp) / f"{i}-{j}" / POLICY.name
                bad.parent.mkdir()
                bad.write_text(source.replace(old, new), encoding="utf-8")
                jobs.append((req, label, kind, bad))

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda job: (job, verdict(job[3], modules[job[0]])), jobs))

    caught, total, missed_lax = 0, 0, []
    for req, _ in MUTANTS:
        print(f"\n{req}")
        for (r, label, kind, _), (said, detail) in results:
            if r != req:
                continue
            if not kind:
                # THE BASELINE. A module that does not hold on the real policy turns every row
                # below into noise: "violated" would mean nothing about the bug.
                if said != "holds":
                    errors.append(f"{req}: does not hold on the policy as written ({said}: {detail})")
                continue
            total += 1
            if said == "violated":
                caught += 1
                print(f"  caught  {label:36} {kind:6}  {detail}")
            elif said == "holds":
                print(f"  MISSED  {label:36} {kind:6}")
                if kind == "lax":
                    missed_lax.append(f"{req}: {label}")
            else:
                errors.append(f"{req} / {label}: verdict not readable: {detail}")
                print(f"  ??      {label:36} {kind:6}  {detail}")

    print(f"\ncaught {caught} of {total} hand-written bugs")
    if missed_lax:
        # Said apart, because these are the ones that let something through.
        print("missed bugs that LET MORE THROUGH:\n" + "\n".join(f"  {m}" for m in missed_lax))
    if errors:
        print("\n" + "\n".join(f"  ERROR  {e}" for e in errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
