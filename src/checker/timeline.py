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
from translator.parse import Unsupported, fmt_window, parse_policies  # noqa: E402
from translator.trace import parse_trace  # noqa: E402

# `@2 (time point 0): DENY  [rules: 4]` -- and `@2 (time point 0): DENY` with no bracket at all.
# THE BRACKET IS OPTIONAL AND ITS ABSENCE IS INFORMATION: a deny by default has no determining
# policy, so the CLI prints none. Requiring it matched nothing on such a trace, which surfaced as
# "replay returned no verdicts" -- a missing verdict rather than the verdict it actually was.
VERDICT = re.compile(r"@(\d+)\s*\(time point (\d+)\):\s*(\w+)(?:\s*\[rules:\s*([^\]]*)\])?")

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


def find_op(node, op: str):
    """The first sub-expression with this `op`, anywhere in a parsed condition.

    Conditions nest through `and`/`or`/`not`/`term`/`agg` and the shape differs per rule, so
    walking generically is more honest than indexing a path that happens to work for one policy.
    """
    if isinstance(node, dict):
        if node.get("op") == op:
            return node
        for v in node.values():
            if (hit := find_op(v, op)) is not None:
                return hit
    elif isinstance(node, list):
        for v in node:
            if (hit := find_op(v, op)) is not None:
                return hit
    return None


def chart_for(policy: Path, rule_index: int | None) -> dict | None:
    """What KIND of picture the deciding rule calls for, and the numbers to draw it with.

    Everything here is read out of the policy by Anchor's own parser rather than typed next to
    the drawing. For an aggregate rule that is the whole chart: which action, which event kind is
    summed over which field, the window, and the threshold it is compared against.

    THE EVENT KIND IS THE POINT. A rule that sums `::request` counts attempts, and a requirement
    that says "transferred" means `::response` -- so the field this returns is the one the finding
    turns on, and a reader can see it without being told what the requirement said.

    Returns None when the policy is outside the parser's subset or the rule is not an aggregate;
    the caller renders what it can rather than guessing.
    """
    if rule_index is None:
        return None
    try:
        rules = parse_policies(policy.read_text(encoding="utf-8"))
    except (Unsupported, Exception):  # noqa: BLE001 -- a chart is never worth failing a run for
        return None
    if rule_index >= len(rules):
        return None

    rule = rules[rule_index]
    chart = {"rule": rule_index, "effect": rule.get("effect"),
             "actions": sorted(rule.get("actions") or []), "kind": None}

    cond = rule.get("cond")
    agg = find_op(cond, "agg")
    if agg is None:
        # A rule gated on something having happened, rather than on a total. The window and the
        # event it looks for are the picture; the POLARITY is the finding, because `unless` and
        # `when` are one word apart and decide opposite ways.
        #
        # Only the top-level negation is read. A `not` nested inside a conjunction would not be
        # reported here, and saying so is better than implying this covers every shape.
        formerly = find_op(cond, "formerly")
        pred = find_op(formerly, "pred") if formerly else None
        if formerly is None or pred is None:
            return chart | {"kind": "predicate"}
        return chart | {
            "kind": "predicate",
            "negated": (cond or {}).get("op") == "not",
            "requires": {
                "action": pred["pred"].get("action"),
                "eventKind": pred["pred"].get("kind"),
                "window": formerly.get("window"),
                "windowText": fmt_window(formerly["window"]),
            },
        }

    inner = agg.get("agg", {})
    pred = find_op(inner.get("cond"), "pred")
    formerly = find_op(inner.get("cond"), "formerly")
    bind = next((b for b in (pred or {}).get("pred", {}).get("binds", [])
                 if b.get("kind") == "var"), None)

    return chart | {
        "kind": "aggregate",
        "aggregate": inner.get("kind"),
        "action": (pred or {}).get("pred", {}).get("action"),
        "eventKind": (pred or {}).get("pred", {}).get("kind"),
        "field": f"{bind['side']}.{bind['field']}" if bind else None,
        "window": (formerly or {}).get("window"),
        "windowText": fmt_window(formerly["window"]) if formerly else None,
        "cmp": agg.get("cmp"),
        "threshold": agg.get("value"),
    }


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
            "rules": [int(r) for r in (rules or "").replace(" ", "").split(",") if r],
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

    # The rule the engine says decided it, not one we picked -- Cedar's "determining policies".
    # NOT filtered to DENY: a claim that says "this must be refused" is broken by an ALLOW, and
    # then the deciding rule is the permit that let it through. Filtering on DENY described only
    # half the findings and left the other half with no chart at all.
    # A deny by default determines nothing, so there is no rule to describe and the chart is None
    # rather than guessed at.
    deciding = next((d["rules"][0] for d in decisions if d["rules"]), None)

    return {
        "generatedBy": "src/checker/timeline.py",
        "chart": chart_for(policy, deciding),
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


def is_witness(d: Path) -> bool:
    """A witness directory answers for itself, and that is what identifies one.

    `witness.py` copies the policy and writes a schema beside the trace precisely so the
    directory can be re-run on its own. So the signature is all three being present, not the
    directory's name -- a `witness` folder missing its schema cannot be replayed and should be
    reported as not found rather than half-processed.
    """
    return (d.is_dir()
            and any(d.glob("*.log")) and any(d.glob("*.dw")) and any(d.glob("*.cedarschema")))


def witnesses(target: Path) -> list[Path]:
    """Every witness at or under `target`, so a whole example directory can be pointed at.

    `examples/aws1` holds the policies; the witnesses are three levels down under `traces/`,
    one per claim that a check found BROKEN. Nobody should have to know that path by heart.
    """
    if is_witness(target):
        return [target]
    return sorted(d for d in target.rglob("*") if is_witness(d))


def emit(data: dict, out: Path, stem: str) -> None:
    body = json.dumps(data, indent=2)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(body + "\n", encoding="utf-8")

    # A page opened from disk cannot fetch() a sibling file -- file:// origins are opaque, so
    # the request fails CORS. Emitting the same data as a script that assigns a global keeps
    # "open the .html and it works" true, which is most of why this artifact is useful at all.
    (out / f"{stem}.js").write_text(
        f"// GENERATED by src/checker/timeline.py from {data['source']['witness']}\n"
        f"// Do not edit. Regenerate instead.\n"
        f"window.ANCHOR_TIMELINE = {body};\n", encoding="utf-8")


def main() -> int:
    # ANCHOR_VERB is set by the launcher, so usage names `anchor timeline` rather than a
    # file the caller never typed. Absent -- run directly -- argparse falls back to argv[0].
    ap = argparse.ArgumentParser(prog=os.environ.get("ANCHOR_VERB") or None,
                                 description=__doc__.splitlines()[0])
    ap.add_argument("target", type=Path,
                    help="a witness directory, or any directory containing them "
                         "(e.g. examples/aws1)")
    ap.add_argument("--name", help="basename for the output; only with a single witness "
                                   "(default: the claim)")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "data",
                    help="directory to write into (default: docs/data)")
    args = ap.parse_args()

    target = args.target.resolve()
    found = witnesses(target)
    if not found:
        print(f"no witness directory at or under {target}.\n"
              f"A witness holds a .log, a .dw and a .cedarschema, and is written by a check that "
              f"found a claim BROKEN -- run `anchor check` with a --property first.", file=sys.stderr)
        return 2
    if args.name and len(found) > 1:
        print(f"--name names one output, but {len(found)} witnesses matched. Point at one of "
              f"them, or drop --name and they are named by their claims.", file=sys.stderr)
        return 2

    for witness in found:
        data = build(witness)
        stem = args.name or data["claim"]
        emit(data, args.out, stem)
        print(f"{stem}.json + {stem}.js -> {args.out.relative_to(REPO)}")
        chart = data["chart"]
        print(f"  {len(data['events'])} events, "
              f"{sum('verdict' in e for e in data['events'])} with a verdict, "
              f"{len(data['rules'])} rules, "
              f"chart: {chart['kind'] if chart else 'none'}")
        if data["source"]["verdictsMissing"]:
            print(f"  NO VERDICTS: {data['source']['verdictsMissing']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
