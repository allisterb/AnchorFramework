"""Turn a witness directory into the data a timeline visualisation draws.

`witness.py` writes a session that breaks a claim, in Dogwood's replay INPUT format, plus
everything needed to re-run it. This reads that directory back and emits the same session as
structured data, with the reference engine's verdict against each decision event.

The point is that the picture is downstream of the artifact. A drawing whose numbers were
typed in by hand is a second copy of the finding, and two copies drift -- the same argument
this repo makes for not having a second session model. So nothing here is authored: the
events come from the `.log` through the translator's own reader, and the verdicts come from
`dogwood replay`. What stays authored is the *interpretation* (which cap, which requirement),
because that is a claim about what the policy was for and no tool can derive it.

Usage:

    ./anchor timeline examples/aws2/traces/agent-policy-CumulativeCap/witness \\
        --name aws2-timeline
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from checker.engine import DOGWOOD, available  # noqa: E402
from translator.trace import parse_trace  # noqa: E402

# `@2 (time point 0): DENY  [rules: 4]`
VERDICT = re.compile(r"@(\d+)\s*\(time point (\d+)\):\s*(\w+)\s*\[rules:\s*([^\]]*)\]")

RULE = re.compile(r"^\s*(permit|forbid)\b", re.MULTILINE)
SCOPE_ACTION = re.compile(r'action\s*==\s*\w+::Action::"([^"]+)"')


def rules_in(text: str) -> list[dict]:
    """Every `permit`/`forbid` in the policy set, indexed the way the engine indexes them.

    `replay` reports `[rules: N]` as a position in the policy set, so the index here has to be
    the position of the statement and nothing else -- not a line number, not a filtered subset.

    The label is the comment directly above the rule, which in a policy written for people is
    the one place its intent is stated in English. Absent, the action name carries it.
    """
    lines = text.splitlines()
    starts = [text[:m.start()].count("\n") for m in RULE.finditer(text)]

    out = []
    for index, line_no in enumerate(starts):
        end = text.find(";", sum(len(x) + 1 for x in lines[:line_no]))
        body = text[sum(len(x) + 1 for x in lines[:line_no]):end if end > 0 else None]

        comment = ""
        probe = line_no - 1
        while probe >= 0 and not lines[probe].strip():
            probe -= 1
        if probe >= 0 and lines[probe].lstrip().startswith("//"):
            comment = lines[probe].lstrip().lstrip("/").lstrip().lstrip("-").strip()

        action = SCOPE_ACTION.search(body)
        out.append({
            "index": index,
            "effect": lines[line_no].strip().split("(")[0].strip(),
            "action": action.group(1) if action else None,
            "label": comment,
            "line": line_no + 1,
        })
    return out


def replay(witness: Path, log: Path, policy: Path, schema: Path) -> tuple[list[dict], str | None]:
    """The reference engine's verdict per decision event, or no verdicts and a reason.

    A missing binary is NOT an error. Everything except the confirmation still works, and the
    same stance is taken in `witness.py` -- a picture without verdicts is worth drawing, a
    picture with invented ones is not.
    """
    cmd = ["replay", "--policy-schema", schema.name, "--trace", log.name, policy.name]
    if not available():
        return [], f"{DOGWOOD} not built, so no verdicts were recorded"

    proc = subprocess.run([str(DOGWOOD), *cmd], cwd=witness, capture_output=True,
                          text=True, timeout=120)
    out = proc.stdout + proc.stderr
    decisions = [
        {
            "at": int(at),
            "timePoint": int(tp),
            "verdict": verdict,
            # Empty means the deny was by default -- no rule decided it, which is a different
            # fact from "a forbid denied it" and has to survive into the data as such.
            "rules": [int(r) for r in rules.replace(" ", "").split(",") if r],
        }
        for at, tp, verdict, rules in VERDICT.findall(out)
    ]
    if not decisions:
        return [], f"replay returned no verdicts: {out.strip()[:200]}"
    return decisions, None


def build(witness: Path) -> dict:
    log = next(iter(sorted(witness.glob("*.log"))), None)
    policy = next(iter(sorted(witness.glob("*.dw"))), None)
    schema = next(iter(sorted(witness.glob("*.cedarschema"))), None)
    for name, found in (("*.log", log), ("*.dw", policy), ("*.cedarschema", schema)):
        if found is None:
            raise SystemExit(f"no {name} in {witness}")

    events = parse_trace(log.read_text(encoding="utf-8"))
    decisions, why_not = replay(witness, log, policy, schema)

    # KEY ON THE TIMESTAMP, NOT THE TIME POINT. The CLI numbers time points sequentially over
    # DECISION events while the trace numbers every event, so the two disagree the moment a
    # session contains anything else -- and joining on the wrong one silently attaches a
    # verdict to the wrong event, which reads exactly like a correct answer.
    verdict_at = {d["at"]: d for d in decisions}

    return {
        "generatedBy": "src/checker/timeline.py",
        "policy": policy.name,
        "claim": log.stem,
        "source": {
            "witness": str(witness.relative_to(REPO)).replace("\\", "/"),
            "trace": log.name,
            "replay": f"dogwood replay --policy-schema {schema.name} "
                      f"--trace {log.name} {policy.name}",
            "verdictsMissing": why_not,
        },
        "rules": rules_in(policy.read_text(encoding="utf-8")),
        "events": [
            {
                "at": e["time"],
                "action": e["action"],
                "kind": e["kind"],
                "input": e["input"],
                "output": e["output"],
                "isDecision": e["decision"],
                **({"verdict": verdict_at[e["time"]]["verdict"],
                    "rules": verdict_at[e["time"]]["rules"]} if e["time"] in verdict_at else {}),
            }
            for e in events
        ],
    }


def main() -> int:
    # ANCHOR_VERB is set by the launcher, so usage names `anchor timeline` rather than a
    # file the caller never typed. Absent -- run directly -- argparse falls back to argv[0].
    ap = argparse.ArgumentParser(prog=os.environ.get("ANCHOR_VERB") or None,
                                 description=__doc__.splitlines()[0])
    ap.add_argument("witness", type=Path, help="a witness directory written by witness.py")
    ap.add_argument("--name", help="basename for the output (default: the claim)")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "data",
                    help="directory to write into (default: docs/data)")
    args = ap.parse_args()

    data = build(args.witness.resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.name or data["claim"]
    body = json.dumps(data, indent=2)

    (args.out / f"{stem}.json").write_text(body + "\n", encoding="utf-8")

    # A page opened from disk cannot fetch() a sibling file -- file:// origins are opaque, so
    # the request fails CORS. Emitting the same data as a script that assigns a global keeps
    # "open the .html and it works" true, which is most of why this artifact is useful at all.
    (args.out / f"{stem}.js").write_text(
        f"// GENERATED by src/checker/timeline.py from {data['source']['witness']}\n"
        f"// Do not edit. Regenerate instead.\n"
        f"window.ANCHOR_TIMELINE = {body};\n", encoding="utf-8")

    print(f"{stem}.json + {stem}.js -> {args.out.relative_to(REPO)}")
    print(f"  {len(data['events'])} events, "
          f"{sum('verdict' in e for e in data['events'])} with a verdict, "
          f"{len(data['rules'])} rules")
    if data["source"]["verdictsMissing"]:
        print(f"  NO VERDICTS: {data['source']['verdictsMissing']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
