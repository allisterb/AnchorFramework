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

WHAT IT WRITES. findings.html beside the findings.md of every policy set it finds a witness in --
one self-contained page per set. `anchor check <dir>` writes the same page as part of an audit; this
redraws it from the witnesses already there, without re-running any check.

Usage:

    ./anchor timeline examples      # findings.html in examples/aws1 and examples/aws2
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
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
from checker import scan as screen  # noqa: E402
from translator.parse import Unsupported, fmt_window, parse_policies  # noqa: E402
from translator.trace import parse_trace  # noqa: E402

# `@2 (time point 0): DENY  [rules: 4]` -- and `@2 (time point 0): DENY` with no bracket at all.
# THE BRACKET IS OPTIONAL AND ITS ABSENCE IS INFORMATION: a deny by default has no determining
# policy, so the CLI prints none. Requiring it matched nothing on such a trace, which surfaced as
# "replay returned no verdicts" -- a missing verdict rather than the verdict it actually was.
VERDICT = re.compile(r"@(\d+)\s*\(time point (\d+)\):\s*(\w+)(?:\s*\[rules:\s*([^\]]*)\])?")

# `[ \t]*`, NOT `\s*`: under MULTILINE, `\s` also matches the newline, so a rule preceded by a
# blank line was matched FROM the blank line -- its line number, effect and label were then read
# off the wrong line. The count stayed right (matches cannot overlap), which is why it went unseen
# until a policy with blank lines between rules came through.
RULE = re.compile(r"^[ \t]*(permit|forbid)\b", re.MULTILINE)
SCOPE_ACTION = re.compile(r'action\s*==\s*\w+::Action::"([^"]+)"')


def rules_in(text: str) -> list[dict]:
    """Every `permit`/`forbid` in the policy set, indexed the way the engine indexes them.

    `replay` reports `[rules: N]` as a position in the policy set, so the index here has to be
    the position of the statement and nothing else -- not a line number, not a filtered subset.

    The label is the comment line nearest above the rule. It is the AUTHOR'S NOTE, not a
    description: comments are a convention, and in a file whose comments head sections rather than
    rules it can be a section title or the last line of a paragraph. What a rule actually does is
    `shape`, read from the parse -- see `describe`.
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
            # Section rulers (`// ---- the reads ----`) carry dashes on both ends.
            comment = lines[probe].lstrip().lstrip("/").strip().strip("-").strip()

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


def describe(rule: dict) -> dict:
    """What one parsed rule does, in the terms a picture needs, read by Anchor's own parser.

    Four kinds:

      unconditional  the rule applies to its actions with no condition at all
      aggregate      a total over past events against a threshold -- which action, which EVENT
                     KIND is summed over which field, the window, the comparison
      predicate      gated on some event having happened within a window, with its POLARITY
      other          a condition this view does not take apart; said, rather than guessed at

    THE EVENT KIND AND THE POLARITY ARE THE POINT. A rule that sums `::request` counts attempts
    where a requirement saying "transferred" means `::response`; a rule gated `unless` where
    `when` was meant decides every case the opposite way. Both are one token in the source and
    both are read straight off the parse, so a reader sees them without being told the intent.

    Only the top-level negation is read as polarity. A `not` nested inside a conjunction is not
    reported, and saying so is better than implying this covers every shape.
    """
    base = {"effect": rule.get("effect"), "actions": sorted(rule.get("actions") or [])}
    cond = rule.get("cond") or {}
    if cond.get("op") == "true":
        return base | {"kind": "unconditional"}

    agg = find_op(cond, "agg")
    if agg is not None:
        inner = agg.get("agg", {})
        pred = find_op(inner.get("cond"), "pred")
        formerly = find_op(inner.get("cond"), "formerly")
        bind = next((b for b in (pred or {}).get("pred", {}).get("binds", [])
                     if b.get("kind") == "var"), None)
        return base | {
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

    formerly = find_op(cond, "formerly")
    pred = find_op(formerly, "pred") if formerly else None
    if formerly is not None and pred is not None:
        return base | {
            "kind": "predicate",
            "negated": cond.get("op") == "not",
            "requires": {
                "action": pred["pred"].get("action"),
                "eventKind": pred["pred"].get("kind"),
                "where": where(pred),
                "window": formerly.get("window"),
                "windowText": fmt_window(formerly["window"]),
            },
        }
    return base | {"kind": "other"}


def where(pred: dict) -> list[dict]:
    """The constraints a predicate puts on the event it looks for, in the policy's own terms.

    Without these a rule reads looser than it is. `formerly within 24h get_client_profile::response`
    is satisfied by ANY profile load; with `{ input.profile_id: context.input.profile_id }` only by
    the one this request names -- and that difference is the whole of an integrity check.

      context   joined to a field of the deciding request (`ctx` in the parse)
      literal   equal to a constant (`lit`)

    A `var` bind names what an aggregate sums and constrains nothing, so it is not listed; `any`
    matches everything and is not a constraint either.
    """
    out = []
    for b in pred["pred"].get("binds", []):
        field = f"{b['side']}.{b['field']}"
        if b.get("kind") == "ctx":
            out.append({"field": field, "context": b["name"]})
        elif b.get("kind") == "lit":
            out.append({"field": field, "literal": b["value"]})
    return out


def parsed(policy: Path) -> tuple[list[dict] | None, str | None]:
    """The policy through Anchor's parser, or no parse and the reason.

    A picture is never worth failing a run for: a policy outside the parser's subset still has a
    trace and verdicts worth drawing, so this reports rather than raises.
    """
    try:
        return parse_policies(policy.read_text(encoding="utf-8")), None
    except Unsupported as e:
        return None, f"outside the parser's subset: {e}"
    except Exception as e:  # noqa: BLE001
        return None, f"parse failed: {type(e).__name__}: {e}"


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
                          text=True, encoding="utf-8", errors="replace", timeout=120)
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


def policy_set(witness: Path) -> Path:
    """The policy directory a witness belongs to: `<set>/traces/<policy>-<Module>/witness`."""
    return witness.resolve().parents[2]


def located(p: Path) -> str:
    """A path as a report should show it: from the repo root inside Anchor, else from the set.

    NEVER `relative_to(REPO)` alone. That raised for every directory outside this checkout -- a
    user's `~/policies`, or `/work` in the container -- which is exactly where reports are for.
    Nor absolute: a report is meant to be sent to someone, and an absolute path puts the sender's
    home directory in it.
    """
    p = p.resolve()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        pass
    for up in p.parents:
        if (up / "traces").is_dir():                     # the set holding this witness
            return p.relative_to(up.parent).as_posix()
    return p.name


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

    text = policy.read_text(encoding="utf-8")
    rules = rules_in(text)
    tree, why_unparsed = parsed(policy)

    # THE TWO INDEXINGS MUST AGREE, OR NOTHING IS DESCRIBED. `rules` is positional over the text,
    # which is how `replay` numbers `[rules: N]`; `tree` is the parser's list. Zipping two lists of
    # different lengths would pin each description onto a neighbouring rule, which reads exactly
    # like a correct answer -- the same failure as joining verdicts on the time point.
    if tree is not None and len(tree) != len(rules):
        why_unparsed = (f"the parser found {len(tree)} rules where the text has {len(rules)}, "
                        f"so none were described rather than risk describing the wrong one")
        tree = None
    if tree is not None:
        for r, p in zip(rules, tree):
            r["shape"] = describe(p)

    chart = ({"rule": deciding} | rules[deciding]["shape"]
             if deciding is not None and deciding < len(rules) and "shape" in rules[deciding]
             else None)

    return {
        "generatedBy": "src/checker/timeline.py",
        "chart": chart,
        "policy": policy.name,
        "claim": log.stem,
        "source": {
            "witness": located(witness),
            "set": located(policy_set(witness)),
            "trace": log.name,
            "replay": f"dogwood replay --policy-schema {schema.name} "
                      f"--trace {log.name} {policy.name}",
            "verdictsMissing": why_not,
            "shapesMissing": why_unparsed,
        },
        "rules": rules,
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


# ------------------------------------------------------------------------------ the report ---

REPORT = Path(__file__).resolve().parent / "report"

LEGEND = """      <div class="legend">
        <span><i class="dot request"></i>::request &mdash; an attempt</span>
        <span><i class="dot response"></i>::response &mdash; it completed</span>
        <span><i class="dot error"></i>::error &mdash; it was refused</span>
        <span><i class="swatch"></i>the window a predicate rule looks back over</span>
      </div>"""

SECTION = """
<section class="finding" data-finding>
  <h2 class="claim">{claim}</h2>
  <p class="sub" data-part="subtitle"></p>
  <div data-part="content" hidden>
    <div class="panel">
      <h3>The session</h3>
      <svg data-part="timeline" viewBox="0 0 860 280" role="img"></svg>
{legend}
    </div>
    <div class="panel" data-part="chart-panel">
      <h3 data-part="chart-heading"></h3>
      <svg data-part="chart" viewBox="0 0 860 240" role="img"></svg>
    </div>
    <div class="panel" data-part="rules-panel">
      <h3 data-part="rules-heading"></h3>
      <ul class="rules" data-part="rules"></ul>
      <p class="footnote">Whether a rule matched is read off the verdict, not re-evaluated here:
        the engine reports Cedar's determining set &mdash; the matching forbids when any forbid
        matched, the matching permits otherwise, and nothing when a deny was by default.</p>
    </div>
    <div class="panel">
      <h3>What decided it</h3>
      <p data-part="why-rule"></p>
      <p data-part="why-consequence"></p>
    </div>
    <footer data-part="provenance"></footer>
  </div>
  <div class="panel missing" data-part="missing">This finding could not be drawn: its script did
    not run. Open the page in a browser with JavaScript enabled.</div>
  <script type="application/json">{data}</script>
</section>"""


def asset(name: str) -> str:
    """A renderer file, refused if it holds what would break it once inlined into a page.

    Inside a <script> element the first closing script tag ends it whatever the JavaScript around
    it meant, and an HTML comment opener changes how the rest is parsed; <style> has the same
    trap. The renderer's own header says never to write either, and this is what enforces it.
    """
    text = (REPORT / name).read_text(encoding="utf-8")
    closing = "</script" if name.endswith(".js") else "</style"
    if closing in text.lower() or "<!--" in text:
        raise SystemExit(f"{REPORT / name} contains {closing}> or <!--, so it cannot be inlined")
    return text


def csp_hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def json_block(data: dict) -> str:
    """Data for a <script type="application/json"> block, which cannot be ended early.

    The block is parsed as HTML first, and the HTML parser ends it at the first closing script tag
    whatever JSON string that tag sits inside -- so a rule comment reading `</script><script>...`
    would otherwise walk straight out of the data and into the page. `<`, `>` and `&` become
    JSON unicode escapes, which JSON.parse turns back into the same characters; ensure_ascii escapes
    U+2028/2029 and everything else outside ASCII.
    """
    return (json.dumps(data, ensure_ascii=True, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def scan_panel(report, notes: list[str]) -> str:
    e = html.escape
    flagged = bool(report.high or report.medium)
    parts = [f'<div class="panel{" flagged" if flagged else ""}">', "  <h3>Input scan</h3>",
             f"  <p>{e(report.summary())}.</p>"]
    parts += [f"  <p><b>{e(n)}</b></p>" for n in notes]
    if report.hits:
        rows = "".join(
            f'<tr><td><code>{e(h.path)}</code></td><td>{h.line}</td>'
            f'<td class="sev-{e(h.severity)}">{e(h.severity)}</td><td>{e(h.kind)}</td>'
            f'<td class="snippet">{e(h.what)}'
            + (f"<br><code>{e(h.snippet)}</code>" if h.snippet else "") + "</td></tr>"
            for h in report.hits)
        parts += ['  <table class="findings"><thead><tr><th>file</th><th>line</th>'
                  "<th>severity</th><th>kind</th><th>what</th></tr></thead>",
                  f"  <tbody>{rows}</tbody></table>"]
    parts += ['  <p class="footnote">What this looks for &mdash; hidden and reordering characters, '
              "look-alike letters in names, instructions aimed at a model, markup, terminal "
              "escapes and encoded payloads &mdash; is in <code>src/checker/scan.py</code>; "
              "<code>anchor scan</code> prints it.</p>", "</div>"]
    return "\n".join(parts)


def write_report(out: Path, *, inputs: Path | None = None, datas: list[dict] | None = None,
                 findings: list[str] | None = None, notes: list[str] | None = None) -> Path:
    """findings.html beside findings.md: one page, needing nothing beside it.

    ONE FILE, so it can be attached to a ticket or sent to someone, and opens the same from disk as
    from a server. Everything is inline: the renderer and its stylesheet, and each finding's data
    as a JSON block the renderer parses and never executes.

    The Content-Security-Policy allows exactly the SHA-256 of the inlined renderer and stylesheet
    and nothing else -- no other script, no inline handler, no style attribute, no network. The
    page quotes a policy someone chose to analyse, often because they do not trust it; escaping is
    the first layer, and this is the one that holds if escaping ever misses.

    `inputs` is where the policies are, for the input scan -- the same place as `out` unless the
    audit was pointed elsewhere with --output-dir.
    """
    inputs = inputs or out
    if datas is None:
        found = witnesses(out / "traces") if (out / "traces").is_dir() else []
        datas = [build(w) for w in found]
    screen_report = screen.scan([inputs], relative_to=inputs)
    js, css = asset("timeline.js"), asset("timeline.css")
    e = html.escape

    checked = ""
    if findings is not None:
        items = "".join(f"<li>{e(f)}</li>" for f in findings)
        checked = ('<div class="panel">\n  <h3>What the checks found</h3>\n'
                   + (f'  <ol class="checked">{items}</ol>' if findings else
                      "  <p>Nothing to look at, within the bounds each check reports.</p>")
                   + "\n  <p class=\"footnote\">The reasoning behind each is in findings.md.</p>\n</div>")

    sections = "".join(SECTION.format(claim=e(d["claim"]), legend=LEGEND, data=json_block(d))
                       for d in datas)
    if not datas:
        sections = ('\n<div class="panel">\n  <h3>Sessions</h3>\n  <p>No claim was found broken, '
                    "so there is no session to draw. A broken claim leaves a witness under "
                    "<code>traces/</code>, and this page draws each one.</p>\n</div>")

    csp = (f"default-src 'none'; script-src {csp_hash(js)}; style-src {csp_hash(css)}; "
           f"img-src 'none'; base-uri 'none'; form-action 'none'")
    name = inputs.resolve().name
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Findings &mdash; {e(name)}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <h1>Findings &mdash; <code>{e(name)}</code></h1>
  <p class="sub">{len(datas)} broken claim{"" if len(datas) == 1 else "s"} drawn below, each with
    the session that breaks it and the reference engine&rsquo;s verdict on that session. The
    written report is <code>findings.md</code>, beside this file.</p>
{scan_panel(screen_report, notes or [])}
{checked}
{sections}
</div>
<script>{js}</script>
</body>
</html>
"""
    path = out / "findings.html"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    return path


def main() -> int:
    # ANCHOR_VERB is set by the launcher, so usage names `anchor timeline` rather than a
    # file the caller never typed. Absent -- run directly -- argparse falls back to argv[0].
    ap = argparse.ArgumentParser(prog=os.environ.get("ANCHOR_VERB") or None,
                                 description=__doc__.splitlines()[0])
    ap.add_argument("target", type=Path,
                    help="a policy directory a check has run on, a witness directory, or any "
                         "directory containing them (e.g. examples)")
    args = ap.parse_args()

    target = args.target.resolve()
    found = witnesses(target)
    if not found:
        print(f"no witness directory at or under {target}.\n"
              f"A witness holds a .log, a .dw and a .cedarschema, and is written by a check that "
              f"found a claim BROKEN -- run `anchor check` with a --property first.", file=sys.stderr)
        return 2
    built = {w: build(w) for w in found}
    for data in built.values():
        for gap in ("verdictsMissing", "shapesMissing"):
            if data["source"][gap]:
                print(f"  {data['claim']} {gap}: {data['source'][gap]}", file=sys.stderr)

    # One report per policy set, beside the findings.md a check wrote there.
    for s in sorted({policy_set(w) for w in found}):
        mine = [built[w] for w in found if policy_set(w) == s]
        path = write_report(s, datas=mine)
        print(f"{shown(path)}  ({len(mine)} finding{'' if len(mine) == 1 else 's'} drawn)")

    return 0


def shown(p: Path) -> Path:
    """`p` relative to the repo where it can be, and as given where it cannot."""
    try:
        return p.resolve().relative_to(REPO)
    except ValueError:
        return p


if __name__ == "__main__":
    raise SystemExit(main())
