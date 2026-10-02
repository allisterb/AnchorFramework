"""Conformance: does Anchor reproduce AWS's own statement of how AgentCore decides?

Step 2 of the AgentCore plan (docs/agent/HANDOFF.md, docs/agentcore.md). The two AgentCore guide
pages with worked temporal examples state the expected behaviour themselves -- as decision tables,
and as prose just as exact ("the fourth call in a window is the first to be denied"). Each example
is transcribed under tests/policies/agentcore/ with AWS's policy text VERBATIM, scopes and
`eventResource` joins included, and its expected decisions as `//|` lines in the same file:

    //| row aws-table: <the table row, in AWS's words>
    //| @0  request  approve_claim  { claimId: "CLM-1" }  ALLOW aws-prose
    //| @1  response approve_claim  { claimId: "CLM-1" } -> { claimId: "CLM-1" }
    //| @10 request  disburse_payment { claimId: "CLM-1" }  DENY

Each row is one session, with one principal, against the gateway the policies are scoped to. Every
request carries its expected decision, so the history is checkable: a response may only follow a
request that was allowed. Each decision is tagged with where its expectation comes from --
`aws-table`, `aws-prose`, or `ours` -- defaulting to the row's tag. The ground truth is AWS's;
anything marked `ours` is a derivation, and is held to a lower standard until `dogwood replay`
(step 3) has confirmed it.

TWO MODES:

    python tests/strands/agentcore_conformance.py              # the policies as AWS publishes them
    python tests/strands/agentcore_conformance.py --stripped   # gateway scope and joins removed

Verbatim is what "done" means: AWS's text as published, under AgentCore's event schema
(`src/translator/agentcore.dwschema`) and AgentCore's own rules (`translator.agentcore`). Every case
was refused there until step 4 modelled that layer. `--stripped` removes the two AgentCore
constructs -- `resource == AgentCore::Gateway::"..."` and `eventResource: resource` -- and reads
under Dogwood's shipped session-pinned preset, which is AgentCore's schema with the scope fields
under Dogwood's names. With one gateway in play that removal changes no decision
(docs/agentcore.md, question 3), so the two runs reach the same semantics by two routes, and a
failure in one and not the other says which half broke.

Exit code: 0 every case conforms; 1 a disagreement, or the ground truth itself is malformed;
2 a case that should have been checked was refused, so no verdict was produced for it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "policies" / "agentcore"
AGENTCORE_SCHEMA = REPO / "src" / "translator" / "agentcore.dwschema"
SESSION_PINNED = (REPO / "ext" / "dogwood" / "dogwood-language" / "configuration"
                  / "event-schemas" / "session-pinned.dwschema")

sys.path.insert(0, str(REPO / "src"))

from dogwood_differential import case_record, check, collect_disagreements, generate_module  # noqa: E402
from checker import table  # noqa: E402
from checker.table import actual  # noqa: E402,F401  -- re-exported for agentcore_replay.py
from translator import Unsupported, apply_pins, parse_policies, parse_schema, parse_trace, stamp_keys  # noqa: E402
from translator.agentcore import refuse_unsound, rejections  # noqa: E402

PRINCIPAL = 'AgentCore::OAuthUser::"alice"'
SOURCES = ("aws-table", "aws-prose", "ours")

# The two guide pages. `rejected/` beside them holds negative checks on the schema, which have no
# decisions to reproduce and are read by agentcore_replay.py alone.
PAGES = ("authoring", "examples")


# ------------------------------------------------------------------------------------------------
# The table format -- rows, events, `finding`, `session=` -- is src/checker/table.py's, which the
# CheckDecisionTable MCP tool uses too. What is here is the suite's own: where its files live, the
# AgentCore names its traces carry, and the two rules it holds its own ground truth to that a
# general table need not meet -- every file names a `target`, and every expectation one of three
# sources.
# ------------------------------------------------------------------------------------------------
def load_suite(suite: Path = SUITE) -> list[dict]:
    """The guide's two pages under the suite; or, for any other directory, every `.dw` in it."""
    if any((suite / page).is_dir() for page in PAGES):
        return [load(p) for page in PAGES for p in sorted((suite / page).glob("*.dw"))]
    return [load(p) for p in sorted(suite.glob("*.dw"))]


def load(path: Path) -> dict:
    """One example: its policy text, and the ground truth read out of its `//|` lines."""
    text = path.read_text(encoding="utf-8")
    gateway = re.search(r'AgentCore::Gateway::"([^"]+)"', text)
    # A policy set with no gateway in any scope -- the blog post's policies 2-6 -- applies at
    # whichever gateway it is deployed on; the article's own placeholder names that one.
    case = table.parse_table(text)
    case.update(name=f"{path.parent.name}/{path.stem}", path=path, text=text,
                gateway=gateway.group(1) if gateway else "<GATEWAY_ARN>")
    return case


def consistency(case: dict) -> list[str]:
    """The format's own rules, and this suite's two stricter ones."""
    problems = table.consistency(case)
    if not case["target"]:
        problems.append("no `//| target`")
    if case["refused"] and case["rows"]:
        problems.append("`expect refused` with rows to check")
    for r, row in enumerate(case["rows"], 1):
        if row["source"] not in SOURCES:
            problems.append(f"row {r}: source {row['source']!r} is not one of {', '.join(SOURCES)}")
        for e in row["events"]:
            if e["source"] not in SOURCES:
                problems.append(f"row {r}, line {e['line']}: source {e['source']!r} is not one of "
                                f"{', '.join(SOURCES)}")
    return problems


# ------------------------------------------------------------------------------------------------
def strip(text: str) -> str:
    """The policy text with AgentCore's gateway scope and `eventResource` joins removed.

    Exactly the transformation `examples/aws1` makes by hand, and safe for the same reason: every
    event in a one-gateway model is at that gateway, so the scope always holds and the join always
    matches.
    """
    text = re.sub(r'resource\s*==\s*AgentCore::Gateway::"[^"]*"', "resource", text)
    text = re.sub(r"eventResource:\s*resource\s*,\s*", "", text)
    text = re.sub(r",\s*eventResource:\s*resource", "", text)
    return re.sub(r"\{\s*eventResource:\s*resource\s*\}", "{ }", text)


def trace(case: dict, row: dict, stripped: bool) -> list[str]:
    """The row as Dogwood trace lines -- the format `dogwood replay` reads.

    The scope fields carry AgentCore's names verbatim and Dogwood's under `--stripped`, matching
    the schema each mode reads under.
    """
    names = ("callerPrincipal", "callerResource") if stripped else ("eventPrincipal", "eventResource")
    return table.trace(case, row, namespace="AgentCore", principal=PRINCIPAL,
                       gateway=f'AgentCore::Gateway::"{case["gateway"]}"', names=names)


def translate(case: dict, stripped: bool) -> tuple[list[str], str | None]:
    """The case's rows as TLA+ records for one shared TLC run, or the reason Anchor refused it."""
    schema_text = (SESSION_PINNED if stripped else AGENTCORE_SCHEMA).read_text(encoding="utf-8")
    try:
        schema = parse_schema(schema_text)
        policies = parse_policies(strip(case["text"]) if stripped else case["text"],
                                  scope_fields=schema["scope_fields"])
        if not stripped:
            # The AgentCore reading in full: its two refusals, and its creation-time rules -- an
            # example AWS publishes must not be one AgentCore would refuse to create.
            refuse_unsound(policies)
            rejected, _ = rejections(policies)
            if rejected:
                raise Unsupported("AgentCore would reject it: " + "; ".join(rejected))
        apply_pins(policies, schema)
        if schema["keys"]:
            stamp_keys(policies, schema["keys"])
        records = []
        for n, row in enumerate(case["rows"], 1):
            events = parse_trace("\n".join(trace(case, row, stripped)), schema.get("paths"))
            oracle = {i + 1: actual(e)
                      for i, e in enumerate(row["events"]) if e["kind"] == "request"}
            if len(events) != len(row["events"]):
                raise Unsupported("the trace did not round-trip through the trace parser")
            records.append(case_record(f"{case['name']}#{n}", policies, events, oracle))
        return records, None
    except Unsupported as e:
        return [], str(e)


# ------------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stripped", action="store_true",
                    help="remove the gateway scope and eventResource joins, and read under "
                         "Dogwood's session-pinned preset")
    # For mutation-checking the harness: a copy of the suite with one expectation flipped must
    # DISAGREE, or "agrees" means nothing.
    ap.add_argument("--suite", type=Path, default=SUITE, help=argparse.SUPPRESS)
    args = ap.parse_args()

    cases = load_suite(args.suite)
    if not cases:
        print(f"no cases under {args.suite}", file=sys.stderr)
        return 1

    malformed = {c["name"]: consistency(c) for c in cases}
    malformed = {k: v for k, v in malformed.items() if v}
    if malformed:
        print("THE GROUND TRUTH IS MALFORMED -- nothing was checked:\n")
        for name, problems in malformed.items():
            for p in problems:
                print(f"  {name}: {p}")
        return 1

    decisions = [e for c in cases for row in c["rows"] for e in row["events"] if e["kind"] == "request"]
    by_source = {s: sum(e["source"] == s for e in decisions) for s in SOURCES}
    findings = sum(e["finding"] for e in decisions)
    print(f"{len(cases)} examples, {sum(len(c['rows']) for c in cases)} sessions, "
          f"{len(decisions)} expected decisions "
          f"({', '.join(f'{n} {s}' for s, n in by_source.items())})"
          + (f", {findings} of them FINDINGS -- the policy does the opposite of what its source "
             f"says, and is held to that" if findings else ""))
    print(f"mode: {'STRIPPED -- gateway scope and eventResource joins removed' if args.stripped else 'VERBATIM -- as AWS publishes them'}\n")

    records, refused, wrongly_checked = [], {}, []
    for c in cases:
        recs, reason = translate(c, args.stripped)
        if reason is not None:
            refused[c["name"]] = reason
        elif c["refused"]:
            wrongly_checked.append(c["name"])
        records += recs

    agreed, disagreements = True, []
    if records:
        agreed, output = check(generate_module(records))
        disagreements = collect_disagreements(output)
        if not agreed and not disagreements:
            print(output[-1500:])

    failing = {d.split("#")[0].strip().strip('"') for d in disagreements}
    for c in cases:
        name = c["name"]
        if name in refused:
            mark = "refused, as expected" if c["refused"] else "REFUSED"
            print(f"  {name:32} {mark}: {refused[name][:90]}")
        elif c["refused"]:
            print(f"  {name:32} CHECKED, but AWS's example needs a construct Anchor should refuse")
        else:
            n = sum(e["kind"] == "request" for row in c["rows"] for e in row["events"])
            print(f"  {name:32} {'DISAGREES' if name in failing else 'agrees'} ({n} decisions)")

    if disagreements:
        print("\ndisagreements (case#session, decision index, expected vs model):")
        for d in disagreements:
            # The assertion is shared with the corpus differential, where the oracle is Dogwood.
            # Here it is AWS's statement, or ours where the row says so.
            print(f"  {d.replace('dogwood says', 'expected')}")

    unexpected = [n for n in refused if not next(c for c in cases if c["name"] == n)["refused"]]
    print(f"\n{len(cases) - len(refused)} checked, {len(refused)} refused "
          f"({len(refused) - len(unexpected)} as expected)")
    if not agreed or wrongly_checked:
        return 1
    if unexpected:
        return 2
    print("every example conforms: Anchor reproduces every decision AWS states"
          + (f", and every one of the {findings} findings where the policy does otherwise"
             if findings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
