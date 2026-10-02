"""Check a policy set against a DECISION TABLE: sessions of requests, each with the decision it should get.

    python src/checker/table.py policy.dw --table expected.table
    python src/checker/table.py policy.dw --table expected.table --json

WHY A TABLE. A validated policy is a legal policy, not a correct one, and the step between -- does
it do what its author meant -- is the one no validator takes. A decision table is the cheapest
statement of intent there is: a session, and ALLOW or DENY. A compliance team can write one, an
author can approve one, and AWS's own posts print them beside their policies. Writing it is the
part a person has to do; checking it is mechanical, so this does that:

    each row ──> a Dogwood trace ──┬──> Anchor's model: the verdict, and which rules decided it
                                   └──> the Dogwood engine (`dogwood replay`): the same two
                                                       │
                       every decision, against the table AND the two against each other

A decision where the model and the engine disagree WITH EACH OTHER is a defect in Anchor, not a
finding about the policy, and is reported as one.

THE FORMAT. One event per line, optionally prefixed `//|` so a table can sit in a `.dw` file's
comments:

    row <source>: what this session is, in words
    @0  request  verify_identity    { account: "A-1" }  ALLOW
    @1  response verify_identity    { account: "A-1" } -> { verified: true }
    @5  request  initiate_transfer  { account: "A-1", amount: 100 }  ALLOW
    @9  session=s2 request initiate_transfer { account: "A-1", amount: 100 }  DENY

Timestamps are seconds. A request carries its expected decision; a response or an error is history
and carries none. `session=s2` puts an event in a second session. `<source>` says where the
expectation came from (`table`, `prose`, `ours` -- any word); a line may name its own. `finding`
after a verdict marks a decision the policy is KNOWN to decide the other way, and holds both
checkers to that. `target <T>` prefixes tool names with `<T>___`, AgentCore's naming for an MCP
target's tools; without it, names are written as they stand.

Before anything is asked of either checker, each row must be a history the gateway could record: a
response only after a request the policy allows, every request with a decision. A wrong row is a
wrong oracle, and it would blame the policy for a transcription slip.

Exit: 0 every decision agrees with the table; 1 one does not, or the model and the engine disagree;
2 no verdict -- the table is malformed, the policy refused, or one AgentCore would not create.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translator import (DEFAULT_MAX_WINDOW, Unsupported, apply_pins, parse_policies,  # noqa: E402
                        parse_schema, parse_trace, stamp_keys, vocabulary)
from translator.agentcore import (AGENTCORE_SCHEMA, is_agentcore, refuse_unsound,  # noqa: E402
                                  rejections, uses_agentcore_fields)
from translator.cases import case_record, evaluate  # noqa: E402
from translator.parse import DEFAULT_SCOPE_FIELDS  # noqa: E402
from translator.trace import parse_fields  # noqa: E402
from checker.engine import DOGWOOD  # noqa: E402
from checker.witness import reading_schema  # noqa: E402

SESSION = "s1"

ROW = re.compile(r"row\s+(\S+):\s*(.+)")
EVENT = re.compile(r"@(\d+)(?:\s+session=(\w+))?\s+(request|response|error)\s+(\w+)\s+(\{[^{}]*\})"
                   r"(?:\s*->\s*(\{[^{}]*\}))?"
                   r"(?:\s+(ALLOW|DENY)(?:\s+(?!finding\b)(\S+))?(?:\s+(finding))?)?\s*$")


# ------------------------------------------------------------------------------------------------
# The format
# ------------------------------------------------------------------------------------------------
def actual(e: dict) -> bool:
    """Whether the policy ALLOWS this decision, as far as the table is concerned.

    The verdict on a line is what the source says should happen; `finding` marks a decision the
    policy is known to decide the other way, so the policy's expected behaviour is the opposite.
    """
    return (e["verdict"] == "ALLOW") != e.get("finding", False)


def parse_table(text: str) -> dict:
    """The rows of a table. Reads only `//|` lines if there are any, so a table can live in a `.dw`."""
    case = {"rows": [], "problems": [], "target": None, "refused": False}
    marked = any(line.startswith("//|") for line in text.splitlines())

    for n, line in enumerate(text.splitlines(), 1):
        if marked:
            if not line.startswith("//|"):
                continue
            line = line[3:]
        body = line.strip()
        if not body or (not marked and body.startswith(("#", "//"))):
            continue
        if body.startswith("target "):
            case["target"] = body.split()[1]
        elif body == "expect refused":
            case["refused"] = True
        elif m := ROW.fullmatch(body):
            case["rows"].append({"source": m.group(1), "title": m.group(2), "events": []})
        elif m := EVENT.fullmatch(body):
            if not case["rows"]:
                case["problems"].append(f"line {n}: an event before any row")
                continue
            t, session, kind, tool, inp, out, verdict, source, finding = m.groups()
            case["rows"][-1]["events"].append({
                "time": int(t), "session": session or SESSION,
                "kind": kind, "tool": tool, "input": inp, "output": out,
                "verdict": verdict, "source": source or case["rows"][-1]["source"],
                "finding": bool(finding), "line": n})
        else:
            case["problems"].append(f"line {n}: not a table line: {body[:60]}")
    return case


def consistency(case: dict) -> list[str]:
    """What makes each row a history the gateway could actually have recorded."""
    problems = list(case["problems"])
    if not case["refused"] and not case["rows"]:
        problems.append("no rows")

    for r, row in enumerate(case["rows"], 1):
        where = f"row {r}"
        last, open_requests = -1, []
        for e in row["events"]:
            at = f"{where}, line {e['line']}"
            if e["time"] <= last:
                problems.append(f"{at}: @{e['time']} is not after @{last}")
            last = e["time"]

            if e["kind"] == "request":
                if not e["verdict"]:
                    problems.append(f"{at}: a request with no expected decision")
                if e["output"]:
                    problems.append(f"{at}: a request carries no output")
                open_requests.append(e)
                continue

            if e["verdict"]:
                problems.append(f"{at}: a {e['kind']} is history-only and is not decided")
            if e["kind"] == "error" and e["output"]:
                problems.append(f"{at}: an error carries no output")
            # The request this event answers: the most recent unanswered one for the same tool,
            # input and session, since the gateway records the request's input on both.
            match = next((q for q in reversed(open_requests)
                          if q["tool"] == e["tool"] and q["input"] == e["input"]
                          and q["session"] == e["session"]), None)
            if match is None:
                problems.append(f"{at}: a {e['kind']} with no earlier matching request")
                continue
            open_requests.remove(match)
            # A response only for a request the policy allows. An error answers either a denial
            # or a permitted call whose tool failed, so it constrains nothing here.
            if e["kind"] == "response" and not actual(match):
                problems.append(f"{at}: a response for a request the policy DENIES")
            e["requestId"] = f"r{match['time']}"
    return problems


def action_name(case: dict, tool: str) -> str:
    """`target T` prefixes a bare tool name with `T___`; otherwise names stand as written."""
    target = case.get("target")
    return tool if target in (None, "-") or "___" in tool else f"{target}___{tool}"


def trace(case: dict, row: dict, *, namespace: str, principal: str, gateway: str,
          names: tuple[str, str] = ("callerPrincipal", "callerResource"),
          session: bool = True) -> list[str]:
    """The row as Dogwood trace lines -- the format `dogwood replay` reads.

    `names` are the scope fields as the event schema spells them. `sessionId` rides on the payload
    and, for a decision, on the request context too, which is where a `pin sessionId =
    context.sessionId` reads its two sides; `session=False` leaves it off for a schema with no such
    pin.
    """
    p, r = names
    scope = f"scope(principal: {principal}, resource: {gateway})"
    lines = []
    for e in row["events"]:
        action = f'{namespace}::Action::"{action_name(case, e["tool"])}"::{e["kind"]}'
        request_id = f"r{e['time']}" if e["kind"] == "request" else e.get("requestId", "")
        sid = f', sessionId: "{e["session"]}"' if session else ""
        payload = (f"input: {e['input']}" + (f", output: {e['output']}" if e["output"] else "")
                   + f', {p}: {principal}, {r}: {gateway}, requestId: "{request_id}"{sid}')
        context = (f'request_context(input: {e["input"]}{sid}) ' if e["kind"] == "request" else "")
        lines.append(f"@{e['time']} {scope} {context}{action}({payload})")
    return lines


# ------------------------------------------------------------------------------------------------
# The engine
# ------------------------------------------------------------------------------------------------
CEDAR_TYPES = {bool: "Bool", int: "Long", str: "String"}


def action_schema(case: dict, policies: list[dict], namespace: str, session: bool) -> str:
    """A Cedar action schema, generated from the policy's actions and the table's own fields.

    `dogwood replay` needs one. Every field is optional -- a table names only what its rows are
    about -- and its type is read off the values the table gives it. A schema the deployment
    actually uses is better, and is taken whenever one is given.
    """
    fields: dict[str, dict[str, dict[str, str]]] = {}
    for row in case["rows"]:
        for e in row["events"]:
            a = fields.setdefault(action_name(case, e["tool"]), {"input": {}, "output": {}})
            for side, rec in (("input", e["input"]), ("output", e["output"])):
                if rec:
                    for k, v in parse_fields(rec[1:-1]).items():
                        a[side].setdefault(k, CEDAR_TYPES.get(type(v), "String"))
    for name in vocabulary(policies, 2, 64)["actions"]:
        fields.setdefault(name, {"input": {}, "output": {}})

    def record(rec: dict[str, str]) -> str:
        return "{ " + ", ".join(f"{k}?: {t}" for k, t in sorted(rec.items())) + " }"

    sid = ", sessionId: String" if session else ""
    actions = "\n".join(
        f'  action "{a}" appliesTo {{ principal: [OAuthUser], resource: [Gateway],\n'
        f"    context: {{ input: {record(f['input'])}, output?: {record(f['output'])}, "
        f"system: SystemContext{sid} }} }};"
        for a, f in sorted(fields.items()))
    return (f"// Generated by Anchor from the policy and the decision table, for `dogwood replay`.\n"
            f"namespace {namespace} {{\n"
            f"  type SystemContext = {{ now: datetime }};\n"
            f"  entity Gateway;\n"
            f"  entity OAuthUser = {{ id: String }} tags String;\n"
            f"{actions}\n}}\n")


def replay(policy: Path, trace_lines: list[str], action_schema_path: Path,
           event_schema: Path | None) -> dict[int, tuple[bool, set[int]]]:
    """{timestamp: (allowed, determining rules, 1-based)} from the engine, keyed on `@N`."""
    with tempfile.TemporaryDirectory(prefix="anchor-table-") as tmp:
        t = Path(tmp) / "row.log"
        t.write_text("\n".join(trace_lines) + "\n", encoding="utf-8")
        args = [str(DOGWOOD), "replay", str(policy), "--policy-schema", str(action_schema_path),
                *(["--event-schema", str(event_schema)] if event_schema else []),
                "--trace", str(t)]
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"dogwood replay failed: {(proc.stdout + proc.stderr).strip()[:600]}")
    out = {}
    for t, v, rules in re.findall(r"@(\d+) \(time point \d+\): (ALLOW|DENY)(?:\s+\[rules: ([\d, ]*)\])?",
                                  proc.stdout):
        out[int(t)] = (v == "ALLOW", {int(x) + 1 for x in rules.split(",") if x.strip()})
    return out


# ------------------------------------------------------------------------------------------------
# The check
# ------------------------------------------------------------------------------------------------
NAMESPACE = re.compile(r"(\w+(?:::\w+)*)::Action::")


def reading_of(policy_text: str, event_schema: Path | None,
               unpinned: bool) -> tuple[dict, Path | str, str]:
    """(schema, what the engine is told, the reading in words) -- chosen as the checker chooses.

    What the engine is told is a `.dwschema` path, or the name of one of Dogwood's two shipped
    readings ("pinned", "unpinned") to be written out with `reading_schema` -- never nothing, which
    would leave the engine on its own default whichever reading the model used.
    """
    if event_schema is not None:
        schema = parse_schema(event_schema.read_text(encoding="utf-8"))
        return schema, event_schema, event_schema.name
    if uses_agentcore_fields(policy_text):
        return (parse_schema(AGENTCORE_SCHEMA.read_text(encoding="utf-8")), AGENTCORE_SCHEMA,
                "AgentCore's event schema (the policy binds eventResource/eventPrincipal): "
                "history partitioned by session")
    schema = {"keys": [] if unpinned else ["principal"], "partial": {}, "paths": {},
              "max_window": DEFAULT_MAX_WINDOW, "scope_fields": dict(DEFAULT_SCOPE_FIELDS)}
    return (schema, "unpinned" if unpinned else "pinned",
            "unpinned: one global trace" if unpinned else
            "Dogwood's default: callerPrincipal pinned, so history is per principal. Pass the "
            "deployment's event schema if it has another")


def check_table(policy: Path, table_text: str, *, event_schema: Path | None = None,
                policy_schema: Path | None = None, unpinned: bool = False,
                engine: bool = True) -> dict:
    """The table, checked. A JSON-ready document; `answered` is False when no verdict was reached."""
    text = policy.read_text(encoding="utf-8")
    case = parse_table(table_text)
    doc: dict = {"policy": policy.name, "answered": False}

    if problems := consistency(case):
        doc["malformed"] = problems
        return doc

    schema, engine_schema, reading = reading_of(text, event_schema, unpinned)
    doc["reading"] = reading
    try:
        policies = parse_policies(text, "", schema["max_window"], schema["scope_fields"])
        if is_agentcore(schema):
            refuse_unsound(policies)
            rejected, warned = rejections(policies)
            if warned:
                doc["warnings"] = warned
            if rejected:
                doc["rejectedByAgentCore"] = rejected
                return doc
        apply_pins(policies, schema)
        if schema["keys"]:
            stamp_keys(policies, schema["keys"])

        m = NAMESPACE.search(re.sub(r"//[^\n]*", "", text))
        namespace = m.group(1) if m else "Anchor"
        gateway = next((p["resource"] for p in policies if p.get("resource")),
                       f'{namespace}::Gateway::"gw"')
        principal = f'{namespace}::OAuthUser::"alice"'
        surface = {internal: written for written, internal in schema["scope_fields"].items()}
        names = (surface.get("callerPrincipal", "callerPrincipal"),
                 surface.get("callerResource", "callerResource"))
        session = "sessionId" in schema["keys"]

        traces, records = [], []
        for n, row in enumerate(case["rows"], 1):
            lines = trace(case, row, namespace=namespace, principal=principal, gateway=gateway,
                          names=names, session=session)
            events = parse_trace("\n".join(lines), schema.get("paths"))
            if len(events) != len(row["events"]):
                raise Unsupported("a row did not round-trip through the trace parser")
            oracle = {i + 1: actual(e) for i, e in enumerate(row["events"]) if e["kind"] == "request"}
            records.append(case_record(f"row{n}", policies, events, oracle))
            traces.append(lines)
    except Unsupported as e:
        doc["refused"] = str(e)
        return doc

    model = evaluate(records)

    engine_verdicts: list[dict] | None = None
    if engine and DOGWOOD.exists():
        with tempfile.TemporaryDirectory(prefix="anchor-table-schema-") as tmp:
            schema_path = policy_schema
            if schema_path is None:
                try:
                    generated = action_schema(case, policies, namespace, session)
                except Unsupported as e:
                    raise RuntimeError(f"no action schema could be generated for the engine: {e}; "
                                       f"pass the deployment's own") from e
                schema_path = Path(tmp) / "generated.cedarschema"
                schema_path.write_text(generated, encoding="utf-8")
            told = (engine_schema if isinstance(engine_schema, Path)
                    else reading_schema(engine_schema, Path(tmp)))
            doc["engine"] = {"ran": True, "actionSchema": policy_schema.name if policy_schema
                             else "generated from the policy and the table (every field optional)"}
            engine_verdicts = [replay(policy, lines, schema_path, told) for lines in traces]
    else:
        doc["engine"] = {"ran": False, "why": "not asked" if not engine else
                         f"no dogwood binary at {DOGWOOD.name}; build it to have the engine answer too"}

    rows, totals = [], {"decisions": 0, "agree": 0, "disagree": 0, "findings": 0,
                        "modelVersusEngine": 0}
    for n, row in enumerate(case["rows"], 1):
        decisions = []
        for i, e in enumerate(row["events"], 1):
            if e["kind"] != "request":
                continue
            allowed, rules = model[n - 1][i]
            d = {"time": e["time"], "session": e["session"], "tool": e["tool"],
                 "expected": e["verdict"], "source": e["source"], "finding": e["finding"],
                 "model": "ALLOW" if allowed else "DENY", "modelRules": sorted(rules)}
            ok = allowed == actual(e)
            if engine_verdicts is not None:
                got = engine_verdicts[n - 1].get(e["time"])
                d["engine"] = None if got is None else ("ALLOW" if got[0] else "DENY")
                d["engineRules"] = None if got is None else sorted(got[1])
                if got is None or got[0] != allowed:
                    d["modelVersusEngine"] = True
                    totals["modelVersusEngine"] += 1
                ok = ok and got is not None and got[0] == actual(e)
            d["agrees"] = ok
            totals["decisions"] += 1
            totals["agree" if ok else "disagree"] += 1
            totals["findings"] += e["finding"] and ok
            decisions.append(d)
        rows.append({"row": n, "source": row["source"], "title": row["title"],
                     "decisions": decisions})

    doc.update(answered=True, rows=rows, totals=totals)
    return doc


# ------------------------------------------------------------------------------------------------
def render(doc: dict) -> str:
    """The document for a person: every decision, and a summary that does not round anything up."""
    if not doc["answered"]:
        if "malformed" in doc:
            return ("THE TABLE IS MALFORMED -- nothing was checked:\n  "
                    + "\n  ".join(doc["malformed"]))
        if "rejectedByAgentCore" in doc:
            return ("REJECTED BY AGENTCORE: the policy could not be created as written, so nothing "
                    "was checked\n  " + "\n  ".join(doc["rejectedByAgentCore"]))
        return f"REFUSED: the policy is outside the modelled subset\n  {doc.get('refused', '')}"

    out = [f"{doc['policy']}, read under {doc['reading']}"]
    eng = doc["engine"]
    out.append(f"engine: {'replayed, action schema ' + eng['actionSchema'] if eng['ran'] else eng['why']}\n")
    for r in doc["rows"]:
        out.append(f"row {r['row']} [{r['source']}]: {r['title']}")
        for d in r["decisions"]:
            sess = f" session={d['session']}" if d["session"] != SESSION else ""
            want = d["expected"] + (" (known finding: the policy does the opposite)" if d["finding"] else "")
            model = f"model {d['model']} {d['modelRules'] or ''}".rstrip()
            engine = (f"  engine {d['engine']} {d['engineRules'] or ''}".rstrip()
                      if "engine" in d else "")
            mark = "ok" if d["agrees"] else "DISAGREES"
            if d.get("modelVersusEngine"):
                mark = "MODEL AND ENGINE DISAGREE -- a defect in Anchor, not a finding"
            out.append(f"  @{d['time']}{sess} {d['tool']:24} expected {want:9}  {model}{engine}  {mark}")
        out.append("")
    t = doc["totals"]
    out.append(f"{t['decisions']} decisions: {t['agree']} as the table says, {t['disagree']} not"
               + (f"; {t['findings']} of the agreements are known findings" if t["findings"] else "")
               + (f"; the model and the engine disagree on {t['modelVersusEngine']}"
                  if t["modelVersusEngine"] else ""))
    out.append("Rules are 1-based, in the order they appear in the policy file.")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policy", type=Path, help="the .dw policy set")
    ap.add_argument("--table", type=Path, required=True,
                    help="the decision table: a file of rows, or a .dw whose `//|` lines hold them")
    ap.add_argument("--event-schema", type=Path, help="the .dwschema the policy is deployed under")
    ap.add_argument("--unpinned", action="store_true",
                    help="global-trace semantics, for a deployment whose schema has no universal pin")
    ap.add_argument("--policy-schema", type=Path, metavar="FILE.cedarschema",
                    help="the action schema the engine replays against; generated if omitted")
    ap.add_argument("--no-engine", action="store_true", help="the model only, no `dogwood replay`")
    ap.add_argument("--json", action="store_true", help="the result as JSON")
    args = ap.parse_args()

    for f in (args.policy, args.table, args.event_schema, args.policy_schema):
        if f is not None and not f.exists():
            print(f"no such file: {f}", file=sys.stderr)
            return 2
    if args.event_schema and args.unpinned:
        ap.error("--event-schema and --unpinned each choose the reading; pass one")

    try:
        doc = check_table(args.policy, args.table.read_text(encoding="utf-8"),
                          event_schema=args.event_schema, policy_schema=args.policy_schema,
                          unpinned=args.unpinned, engine=not args.no_engine)
    except RuntimeError as e:
        doc = {"policy": args.policy.name, "answered": False, "refused": str(e)}

    print(json.dumps(doc, indent=2) if args.json else render(doc))
    if not doc["answered"]:
        return 2
    t = doc["totals"]
    return 0 if t["disagree"] == 0 and t["modelVersusEngine"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
