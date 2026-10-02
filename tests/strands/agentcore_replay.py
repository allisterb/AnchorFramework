"""Step 3: the Dogwood engine as an oracle for AgentCore's event model.

`agentcore_conformance.py` holds Anchor's model to AWS's decision tables. This holds the ENGINE to
them, under our transcription of AgentCore's event schema -- which tests two things at once:

    the guide's policies, VERBATIM ──┬── dogwood validate ──> accepted?            (the schema)
    agentcore.dwschema                ├── dogwood replay   ──> verdicts == table?   (the schema,
    agentcore.cedarschema             │                                              and the rows)
    the suite's rows, as traces ──────┘

  - VALIDATION corroborates the transcribed schema. AWS's examples were written for AgentCore, so
    if `eventResource: resource` were not a declared field, or the pin were wrong, they would be
    rejected. The negative checks under `rejected/` go further: AWS quotes some of the service's
    rejection messages, and the engine must produce the same ones.
  - REPLAY corroborates the expected decisions -- above all the rows tagged `ours`, which are our
    derivations from the semantics and which nothing else confirms. An `aws-*` row the engine
    disagrees with is a finding about AgentCore or about our reconstruction of it; an `ours` row it
    disagrees with is a mistake of ours.

What this cannot do is confirm that AgentCore's deployed schema IS this one. Only a real gateway
can; see docs/agentcore.md, open question 3.

The policy text is handed to the engine exactly as checked in. The traces are the ones
`agentcore_conformance.py` builds, with AgentCore's field names.

REQUIRES THE BUILT BINARY; skips without it, like `dogwood_replay.py`.

    python tests/strands/agentcore_replay.py

Exit code: 0 the engine agrees with every expected decision and every schema check; 1 a
disagreement, a rejected example, or a negative check that did not reject as AWS says;
2 skipped, no binary.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentcore_conformance import SOURCES, SUITE, actual, consistency, load_suite, trace  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EVENT_SCHEMA = REPO / "src" / "translator" / "agentcore.dwschema"
ACTION_SCHEMA = SUITE / "agentcore.cedarschema"
DOGWOOD = (REPO / "ext" / "dogwood" / "target" / "release"
           / ("dogwood.exe" if sys.platform == "win32" else "dogwood"))

# Set in main(), from --policy-schema.
SCHEMAS = ["--policy-schema", str(ACTION_SCHEMA), "--event-schema", str(EVENT_SCHEMA)]


def dogwood(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(DOGWOOD), *args], capture_output=True, text=True, encoding="utf-8")


def validate(policy: Path) -> tuple[bool, str]:
    proc = dogwood("validate", str(policy), *SCHEMAS)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def replay(policy: Path, trace_path: Path) -> dict[int, bool]:
    """{timestamp: allowed}, keyed on `@N` -- the CLI numbers time points over decisions only."""
    proc = dogwood("replay", str(policy), *SCHEMAS, "--trace", str(trace_path))
    if proc.returncode != 0:
        raise RuntimeError(f"dogwood replay failed:\n{proc.stdout}{proc.stderr}")
    out = {int(t): v == "ALLOW"
           for t, v in re.findall(r"@(\d+) \(time point \d+\): (ALLOW|DENY)", proc.stdout)}
    if not out:
        raise RuntimeError(f"no verdicts parsed from:\n{proc.stdout}")
    return out


def main() -> int:
    import argparse                                                   # noqa: PLC0415

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--suite", type=Path, default=SUITE,
                    help="a directory of cases in the conformance format (default: the guide's)")
    ap.add_argument("--policy-schema", type=Path, default=None, metavar="FILE.cedarschema",
                    help="the action schema the cases' tools are declared in (default: the "
                         "suite's own .cedarschema)")
    args = ap.parse_args()

    action_schema = args.policy_schema or next(iter(sorted(args.suite.glob("*.cedarschema"))),
                                               ACTION_SCHEMA)
    SCHEMAS[1] = str(action_schema)

    if not DOGWOOD.exists():
        print(f"SKIPPED: no dogwood binary at {DOGWOOD.relative_to(REPO)}\n"
              "Build it with:\n"
              "  cargo build --release --locked --manifest-path ext/dogwood/Cargo.toml",
              file=sys.stderr)
        return 2

    cases = load_suite(args.suite)
    malformed = [f"{c['name']}: {p}" for c in cases for p in consistency(c)]
    if malformed:
        print("THE GROUND TRUTH IS MALFORMED -- nothing was replayed:\n  " + "\n  ".join(malformed))
        return 1

    failures, findings = 0, 0
    confirmed, contradicted = Counter(), Counter()
    print(f"validate and replay, verbatim, under agentcore.dwschema + {action_schema.name}\n")

    with tempfile.TemporaryDirectory(prefix="anchor-agentcore-") as tmp:
        trc = Path(tmp) / "t.log"
        for c in cases:
            path = c["path"]
            ok, text = validate(path)
            if c["refused"]:
                # The guardrail examples call AWS's managed provider, which has no declaration we
                # could supply; they are here for Anchor's refusal, not for the engine.
                first = next((ln for ln in text.splitlines() if ln.startswith("error")), text[:80])
                print(f"  {c['name']:32} not replayed (expect refused); validate: "
                      f"{'OK' if ok else first}")
                continue
            if not ok:
                failures += 1
                print(f"  {c['name']:32} REJECTED by the engine -- AWS's example does not validate "
                      f"under our schema:\n{text}")
                continue

            wrong = []
            for n, row in enumerate(c["rows"], 1):
                trc.write_text("\n".join(trace(c, row, stripped=False)) + "\n", encoding="utf-8")
                verdicts = replay(path, trc)
                for e in row["events"]:
                    if e["kind"] != "request":
                        continue
                    got = verdicts.get(e["time"])
                    # At a `finding`, the engine must do the OPPOSITE of what the source says --
                    # that is the finding, confirmed by the engine rather than by our model.
                    if got == actual(e):
                        confirmed[e["source"]] += 1
                        findings += e["finding"]
                    else:
                        contradicted[e["source"]] += 1
                        shown = "nothing" if got is None else ("ALLOW" if got else "DENY")
                        said = (f"the source says {e['verdict']} and the policy was expected to "
                                f"do the opposite" if e["finding"] else f"expected {e['verdict']}")
                        wrong.append(f"session {n} ({row['title'][:50]}), @{e['time']} "
                                     f"{e['tool']}: {said} [{e['source']}], engine {shown}")
            failures += bool(wrong)
            n = sum(e["kind"] == "request" for row in c["rows"] for e in row["events"])
            print(f"  {c['name']:32} {'ENGINE DISAGREES' if wrong else 'agrees'} ({n} decisions)")
            for w in wrong:
                print(f"  {'':32}   {w}")

    rejected = sorted((args.suite / "rejected").glob("*.dw"))
    if rejected:
        print("\nnegative checks -- what AWS says the service rejects, and how:\n")
    for path in rejected:
        expect = next((ln[3:].strip()[len("rejects"):].strip()
                       for ln in path.read_text(encoding="utf-8").splitlines()
                       if ln.startswith("//| rejects")), None)
        ok, text = validate(path)
        good = expect is not None and not ok and expect in text
        failures += not good
        print(f"  rejected/{path.stem:23} {'rejected as AWS quotes' if good else 'DID NOT MATCH'}")
        if not good:
            print(f"  {'':32}   expected a rejection containing: {expect}\n{text}")

    total = sum(confirmed.values()) + sum(contradicted.values())
    print(f"\n{sum(confirmed.values())} of {total} expected decisions confirmed by the engine: "
          + ", ".join(f"{s} {confirmed[s]}/{confirmed[s] + contradicted[s]}" for s in SOURCES)
          + (f"; {findings} of them FINDINGS, where the policy as published does the opposite of "
             f"what its source says" if findings else ""))
    if failures:
        return 1
    print("the engine agrees with every expected decision, AWS's and ours"
          + (", findings included" if findings else "")
          + (", and the schema checks pass" if rejected else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
