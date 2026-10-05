"""Run the harnesses in this directory, in parallel, and say what each one cost.

    python tests/strands/run.py                   all of them, except the opt-in ones
    python tests/strands/run.py pipeline hitl     the ones whose name contains either
    python tests/strands/run.py semantic          an opt-in one, named
    python tests/strands/run.py --workers 4       fewer, when something else wants the machine
    python tests/strands/run.py --list            what would run, and nothing else

WHY THIS EXISTS BESIDE THE xunit SUITE, rather than instead of it. The C# tests are the gate: each
one asserts the FINDING its harness was written to pin, not merely that it exited zero, and a
harness that stopped catching what it was written to catch would pass here and fail there. What
they are not is a development loop -- `dotnet test` builds four projects and runs the Dafny and
spec tests too, which is eight minutes to learn that one harness is still green.

TWO THINGS IT GETS RIGHT THAT RUNNING A HARNESS BY HAND DOES NOT.

    ANCHOR_TLC_JAVA_OPTS.  `-XX:TieredStopAtLevel=1` stops the JVM's optimising compiler, which is
                           worth ~16% on one small model and 1.9x on eight at once -- the suite
                           runs many at once on four physical cores, and each JVM was spending
                           cores optimising code it finishes before benefiting from. It is set by
                           `tests/Anchor.Tests.Verifier/anchor.runsettings` on the TEST HOST, so a
                           harness run by hand simply does not get it and is slower for it. Set
                           here for the same reason, and overridable.

    THE FLAGS.             `event_schema_readings.py` sweeps 48 checker runs without `--quick`.
                           The C# test passes it; running the file by hand does not, and the
                           difference is 217s against 99s.

ON CONCURRENCY, and it is measured rather than guessed. TLC throughput on this machine plateaus at
about 3x by six workers and gains nothing after eight -- ~1.6s of every ~2.0s run is starting a
JVM, and the JVMs contend. So the default is six: past the knee, and leaving something for whatever
else is running.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# Flags a harness needs to run the way the suite runs it. Anything not named here runs bare.
ARGS: dict[str, list[str]] = {
    "event_schema_readings.py": ["--quick"],
}

# Not a harness: this file.
SKIP = {"run.py"}

# Run only when a pattern names them. They measure drafted output rather than pin a finding, so a
# low number is not a failure, and they belong to work on drafting, not to every run.
OPT_IN = {"semantic_mutants.py"}


def harnesses(patterns: list[str]) -> list[Path]:
    """Every runnable harness here, filtered by substring.

    A harness is a file with a `__main__` guard, discovered rather than listed -- a list would
    silently stop covering a file somebody adds, which is the failure mode this whole directory
    exists to avoid in the specs it checks.
    """
    found = [p for p in sorted(HERE.glob("*.py"))
             if p.name not in SKIP
             and '__name__ == "__main__"' in p.read_text(encoding="utf-8")]
    if not patterns:
        return [p for p in found if p.name not in OPT_IN]
    return [p for p in found if any(s in p.name for s in patterns)]


def run_one(path: Path, full: bool) -> tuple[Path, int, float, str]:
    args = [] if full and path.name in ARGS else ARGS.get(path.name, [])
    started = time.monotonic()
    proc = subprocess.run([sys.executable, str(path.relative_to(REPO)), *args],
                          cwd=REPO, capture_output=True, text=True)
    return path, proc.returncode, time.monotonic() - started, proc.stdout + proc.stderr


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("patterns", nargs="*", help="substrings; a harness runs if its name holds one")
    p.add_argument("--workers", type=int, default=6,
                   help="how many at once. Measured: throughput plateaus at ~3x by six "
                        "(default: 6)")
    p.add_argument("--full", action="store_true",
                   help="drop the abbreviating flags -- the full event-schema sweep rather than "
                        "--quick")
    p.add_argument("--list", action="store_true", help="print what would run and stop")
    p.add_argument("--verbose", action="store_true", help="print each harness's whole output")
    args = p.parse_args()

    chosen = harnesses(args.patterns)
    if not chosen:
        print(f"nothing matches {args.patterns}", file=sys.stderr)
        return 2
    if args.list:
        for path in chosen:
            print(f"  {path.name}{' ' + ' '.join(ARGS[path.name]) if path.name in ARGS else ''}")
        return 0

    # THE TEST HOST'S OWN SETTING, and not forced: somebody investigating a JVM question needs to
    # be able to turn it off, and the measurements it rests on are recorded in anchor.runsettings.
    os.environ.setdefault("ANCHOR_TLC_JAVA_OPTS", "-XX:TieredStopAtLevel=1")

    print(f"{len(chosen)} harness(es), {args.workers} at a time  "
          f"[ANCHOR_TLC_JAVA_OPTS={os.environ['ANCHOR_TLC_JAVA_OPTS']}]\n")

    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for path, code, secs, out in pool.map(lambda h: run_one(h, args.full), chosen):
            skipped = "SKIPPED:" in out
            mark = "skip" if skipped else ("ok  " if code == 0 else "FAIL")
            print(f"  {mark}  {path.name:<32} {secs:>6.1f}s"
                  + ("" if code == 0 else f"   exit {code}"))
            results.append((path, code, secs, out, skipped))

    wall = time.monotonic() - started
    serial = sum(r[2] for r in results)
    failed = [r for r in results if r[1] != 0]
    skipped = [r for r in results if r[4]]

    print(f"\n{'-' * 78}")
    print("Slowest:")
    for path, _, secs, _, _ in sorted(results, key=lambda r: -r[2])[:6]:
        print(f"  {secs:>6.1f}s  {path.name}")
    print(f"\n  {wall:.0f}s wall, {serial:.0f}s serial ({serial / wall:.2f}x), "
          f"{len(results) - len(failed) - len(skipped)} passed, {len(skipped)} skipped, "
          f"{len(failed)} failed")

    for path, code, _, out, _ in failed:
        print(f"\n{'=' * 78}\n{path.name} exited {code}\n{'=' * 78}")
        print("\n".join(out.splitlines()[-30:]))

    if args.verbose:
        for path, _, _, out, _ in results:
            print(f"\n{'=' * 78}\n{path.name}\n{'=' * 78}\n{out}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
