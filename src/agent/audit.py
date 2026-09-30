"""Audit a whole directory of policies against the intentions somebody else wrote down.

    python src/agent/audit.py examples/aws1
    python src/agent/audit.py policies/ --output-dir findings --no-llm

AUDIT, AND IT USED TO BE CALLED `auto`. That name claimed the wrong thing. In this field "auto"
means AUTOFORMALIZATION -- the agent doing the formalizing -- and nothing here formalizes anything:
every intentional claim it checks is a `.tla` module a person wrote by hand, paired with the policy
its header names. What was automated was the RUNNING, never the specifying, and a verb that reads
as the second is an overclaim in the one place this project cannot afford one. `pipeline.py` is
where a model drafts a property; this audits what it finds.

An audit is exactly the right word for it: unattended, exhaustive, and checking against criteria it
did not invent.

WHAT IS AUTOMATED AND WHAT IS NOT, because the difference is the whole point of the project.

    automated    running every check, on every policy, and saying what came back
    NOT          deciding what the policy was supposed to mean

A directory with no `.tla` modules gets the derived questions only -- is any rule inert, does any
edit widen -- and the report says so in those words. Those questions are answerable without
knowing intent, which is exactly why they cannot catch a policy that is the opposite of what its
author wanted. Writing the intent down is the part that needs a person, and no verb makes that
untrue.

THE ENUMERATION IS CODE, NOT THE MODEL. Every policy is found by globbing and every check is run
before the model is asked anything. A model deciding which files to check is a model that can skip
one, and a skipped policy in a clean-looking report is worse than no report. The model's job here
is triage and prose: it receives results it did not choose and cannot alter.

IT RUNS WITHOUT AN LLM AT ALL. `--no-llm`, or simply no API key, still produces `findings.md`
and `results.json` from the checks themselves -- which is most of the value and all of the part
that belongs in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

CHECKER = REPO / "src" / "checker" / "properties.py"

from agent.invoke import run_relayed  # noqa: E402
from checker import scan as screen  # noqa: E402
from checker.explain import as_dict, explain_file  # noqa: E402
from checker.witness import Confirmation, confirm, reading_schema  # noqa: E402


def as_finding(c: Confirmation) -> dict:
    """One replayed counterexample, as data. The `sentence` is what a person reads."""
    return {"invariant": c.invariant, "state": c.state, "demanded": c.demanded,
            "engine": c.engine, "confirms": c.agreed, "at": c.at, "events": c.events,
            "why": c.why, "sentence": c.sentence(), "trace": c.trace,
            # Where the runnable files went, and the command that reproduces the verdict from
            # inside that directory. Carried as data so the report prints the real invocation
            # rather than a template somebody has to fill in.
            "directory": c.directory, "command": c.command}

# The findings carry em dashes and policy text; a Windows console defaults to a codepage that
# cannot hold them, and the report then LOOKS corrupted while the file beside it is fine. The
# files are always UTF-8 -- this is only so the summary on the way past is readable too.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# The policy a property module is about, taken from the first `x.dw` named in its header -- the
# convention `properties.py --describe` already emits into every generated skeleton.
POLICY_IN_HEADER = re.compile(r"`([^`]+\.dw)`")

# A questions file is markdown: `### heading`, an optional `*Policy:* \`file.dw\`` line, and the
# question itself as a blockquote. Documented in examples/aws1/questions.md, which is the worked
# example of the format.
QUESTION_HEADING = re.compile(r"^#{2,4}\s+(.*)$")
QUESTION_POLICY = re.compile(r"\*Polic(?:y|ies):\*\s*(.*)$")
BACKTICKED = re.compile(r"`([^`]+)`")


@dataclass
class Question:
    heading: str
    text: str
    policy: str = ""
    against: str = ""


@dataclass
class Plan:
    """What was found in the directory, before anything is run."""

    directory: Path
    # The one policy set a single-set audit is about; empty for a whole directory.
    subject: str = ""
    # Modules named with --property rather than found by header, so the report can say which.
    given: list[Path] = field(default_factory=list)
    policies: list[Path] = field(default_factory=list)
    properties: list[tuple[Path, Path]] = field(default_factory=list)   # (module, policy)
    unpaired: list[tuple[Path, str]] = field(default_factory=list)      # (module, why)
    questions: list[Question] = field(default_factory=list)


def parse_questions(text: str) -> list[Question]:
    """The questions from a markdown file. Empty when it has none, which is not an error."""
    out: list[Question] = []
    heading, policy, against, body = "", "", "", []

    def flush():
        if body and heading:
            out.append(Question(heading=heading, text=" ".join(body).strip(),
                                policy=policy, against=against))

    for line in text.splitlines():
        if (m := QUESTION_HEADING.match(line)):
            flush()
            heading, policy, against, body = m.group(1).strip(), "", "", []
        elif (m := QUESTION_POLICY.search(line)):
            named = BACKTICKED.findall(m.group(1))
            policy = named[0] if named else ""
            against = named[1] if len(named) > 1 else ""
        elif line.startswith(">"):
            body.append(line.lstrip("> ").strip())
    flush()
    return [q for q in out if q.text]


def discover(directory: Path) -> Plan:
    """Everything in the directory this can act on. Globbed, not asked for."""
    plan = Plan(directory=directory)
    plan.policies = sorted(p for p in directory.glob("*.dw"))

    by_name = {p.name: p for p in plan.policies}
    for module in sorted(directory.glob("*.tla")):
        if not module.with_suffix(".cfg").exists():
            plan.unpaired.append((module, "no companion .cfg naming its invariants"))
            continue
        named = POLICY_IN_HEADER.findall(module.read_text(encoding="utf-8", errors="replace")[:2000])
        target = next((by_name[n] for n in named if n in by_name), None)
        if target is None:
            plan.unpaired.append(
                (module, "its header names no policy set in this directory -- add `<policy-set>.dw` to it"))
            continue
        plan.properties.append((module, target))

    questions = directory / "questions.md"
    if questions.exists():
        plan.questions = parse_questions(questions.read_text(encoding="utf-8"))
    return plan


def narrow(plan: Plan, policy: Path) -> Plan:
    """The same plan, about ONE policy set: its modules, and the questions that name it.

    A module that names the set but cannot run -- no .cfg -- is kept as unpaired, so it is reported
    rather than silently dropped. A question with no `*Policy:*` line is left out: in a directory it
    falls to the first policy set, which says nothing about whether it was meant for this one.
    """
    def names_it(module: Path) -> bool:
        head = module.read_text(encoding="utf-8", errors="replace")[:2000]
        return policy.name in POLICY_IN_HEADER.findall(head)

    return Plan(directory=plan.directory, subject=policy.name, policies=[policy],
                properties=[(m, p) for m, p in plan.properties if p == policy],
                unpaired=[(m, why) for m, why in plan.unpaired if names_it(m)],
                questions=[q for q in plan.questions if policy.name in (q.policy, q.against)])


def available(plan: Plan) -> str:
    """What `--full` would add to a plain check: the intentions and questions it did not use.

    Read from headers and questions.md only -- nothing is run -- so a plain check can say what it
    skipped without paying for it. Empty when there is nothing, so a caller prints it as it comes.
    """
    about = f"`{plan.subject}`" if plan.subject else "these policy sets"
    lines = []
    if plan.properties:
        names = [m.name for m, _ in plan.properties]
        shown = ", ".join(names[:6]) + (f", and {len(names) - 6} more" if len(names) > 6 else "")
        lines.append(f"  {len(names)} property module(s) state what {about} should mean: {shown}")
    if plan.unpaired:
        lines.append(f"  {len(plan.unpaired)} more module(s) cannot run as they are, and --full says why: "
                     + ", ".join(m.name for m, _ in plan.unpaired))
    if plan.questions:
        lines.append(f"  {len(plan.questions)} question(s) in questions.md name {about} "
                     f"(asking them uses an LLM; --no-llm skips them)")
    if not lines:
        return ""
    return ("Not checked, and available to --full:\n" + "\n".join(lines)
            + "\n--full checks them and writes the report.")


def run_checker(policy: Path, *, against: Path | None = None, property_module: Path | None = None,
                keep: Path | None = None, attempts: int | None = None,
                smoke: int | None = None, max_fields: int | None = None,
                reading: str | None = None, event_schema: Path | None = None,
                timeout: int = 1800) -> dict:
    """One check, structured. A refusal is data, never an exception."""
    args = [sys.executable, str(CHECKER), str(policy)]
    if property_module is None:
        args.append("--json")
    if against is not None:
        args += ["--against", str(against), "--json"]
    if property_module is not None:
        args += ["--property", str(property_module)]
    if keep is not None:
        args += ["--keep", str(keep)]
    if attempts is not None:
        args += ["--attempts", str(attempts)]
    if max_fields is not None:
        args += ["--max-fields", str(max_fields)]
    # "pinned" or "unpinned", passed to EVERY check -- derived and property alike -- so a report
    # never mixes verdicts from two readings.
    if reading is not None:
        args.append(f"--{reading}")
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]

    # A random walk, for a set too big to exhaust. NOT passed to a --property run: a property is
    # meant to HOLD and its counterexample is the answer, so sampling behaviours would turn "this
    # claim is broken" into "we did not happen to break it", which is not the same sentence.
    if smoke is not None and property_module is None:
        args += ["--smoke", str(smoke)]

    # The checker's progress lines are passed on as they arrive; everything else it says on stderr
    # is carried into the report, so relaying that too would only print it twice.
    proc = run_relayed(args, timeout, relay=lambda line: print(line, file=sys.stderr, flush=True))

    # A property run prints prose, not JSON: its verdict is the exit code and its detail is the
    # BROKEN lines. Carried as text rather than forced into a shape it does not have.
    if property_module is not None:
        return {"kind": "property", "held": proc.returncode == 0, "exitCode": proc.returncode,
                "output": proc.stdout.strip(), "error": proc.stderr.strip()}
    try:
        return {"kind": "derived", **json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"kind": "derived", "_failed": True, "exitCode": proc.returncode,
                "_why": (proc.stderr or proc.stdout).strip()[-1500:]}


def step_summary(result: dict) -> str:
    """One line for a finished step: what came back."""
    if result.get("kind") == "property":
        return "holds" if result.get("held") else "BROKEN"
    if result.get("_failed"):
        return "could not be checked"
    rules = result.get("rules") or []
    verdicts = ", ".join(sorted({str(r.get("verdict")) for r in rules})) or "no rules"
    return f"{len(rules)} rule(s): {verdicts}"


def check_all(plan: Plan, out: Path, attempts: int | None = None,
              smoke: int | None = None, max_fields: int | None = None,
              reading: str | None = None, event_schema: Path | None = None) -> dict:
    """Every check, in a fixed order, before the model is asked anything."""
    traces = out / "traces"
    results: dict = {"directory": str(plan.directory), "derived": {}, "properties": {},
                     # Recorded so the report can say what this run could NOT establish. A smoke
                     # sweep reports `live` or `unknown` and never VACUOUS, REDUNDANT or DEAD --
                     # those are claims of ABSENCE and a random walk cannot make one.
                     "smoke": smoke,
                     # Which event-schema reading every verdict below was computed under.
                     "reading": event_schema.name if event_schema else (reading or "pinned"),
                     "unpaired": [{"module": m.name, "why": w} for m, w in plan.unpaired]}

    # Numbered, because the first answer can be minutes away; `announce` has said what the steps
    # are before this starts.
    steps = len(plan.policies) + len(plan.properties)
    step = 0

    for policy in plan.policies:
        step += 1
        print(f"[{step}/{steps}] {policy.name}: rule by rule", file=sys.stderr, flush=True)
        began = time.monotonic()
        results["derived"][policy.name] = run_checker(
            policy, keep=traces / policy.stem, attempts=attempts,
            smoke=smoke, max_fields=max_fields, reading=reading, event_schema=event_schema)
        print(f"      -> {step_summary(results['derived'][policy.name])} "
              f"({time.monotonic() - began:.0f}s)", file=sys.stderr, flush=True)

    for module, policy in plan.properties:
        step += 1
        print(f"[{step}/{steps}] {policy.name} against {module.name}", file=sys.stderr, flush=True)
        began = time.monotonic()
        checked = run_checker(policy, property_module=module,
                              keep=traces / f"{policy.stem}-{module.stem}", attempts=attempts,
                              max_fields=max_fields, reading=reading, event_schema=event_schema)

        # A BROKEN claim, carried back into the policy's own language and put to the reference
        # engine. Cheap -- the counterexample is already computed and a replay is milliseconds --
        # and it is the difference between a finding a Dogwood author can check and one they
        # cannot. Degrades to the TLA+ counterexample alone when the engine is not built.
        confirmations = []
        if not checked.get("held"):
            try:
                # The engine gets the reading the model was built under, as a file -- never its
                # own default, which is only the same reading by coincidence.
                with tempfile.TemporaryDirectory(prefix="anchor-reading-") as scratch:
                    confirmations = [as_finding(c) for c in
                                     confirm(policy, module, checked.get("output", ""),
                                             keep=traces / f"{policy.stem}-{module.stem}" / "witness",
                                             event_schema=event_schema or reading_schema(
                                                 reading or "pinned", Path(scratch)))]
            except Exception as e:                   # never let the extra step lose the finding
                confirmations = [{"why": f"the counterexample could not be replayed: {e}"}]

        confirmed = sum(1 for c in confirmations if c.get("engine"))
        print(f"      -> {step_summary(checked)}"
              + (f", confirmed by the Dogwood engine" if confirmed else "")
              + f" ({time.monotonic() - began:.0f}s)", file=sys.stderr, flush=True)

        results["properties"][module.name] = {
            "policy": policy.name,
            "given": module in plan.given,
            # READ BEFORE RUN. What the module claims is worked out from its own text, costs
            # nothing, and is the only part of this report a reader can disagree with on sight --
            # "holds" is a fact about a claim nobody has read yet.
            "claims": as_dict(explain_file(module)),
            "witness": confirmations,
            **checked,
        }
    return results


def findings_of(results: dict) -> list[str]:
    """The things a person should look at, in the order they should look at them.

    A BROKEN intentional claim comes first and always: it is the only finding here that means the
    policy does not do what somebody said it does. An inert rule is a defect in the policy; a
    broken property is a defect in the policy OR in the claim, and either way somebody has to
    decide which.
    """
    out = []
    for name, r in results.get("properties", {}).items():
        if r.get("held"):
            continue

        # THE CONCRETE ONE FIRST, when there is one. "A stated intention is not met" is true and
        # unusable; "with gap = 960 the Dogwood engine ALLOWS this, and your claim says it must
        # REFUSE it" is the same finding in the language the policy was written in, and it names
        # a value somebody can go and try.
        said = [w["sentence"] for w in (r.get("witness") or []) if w.get("sentence")]
        if said:
            out += [f"**{r['policy']} does not satisfy {name}** — {s}" for s in said]
        else:
            out.append(f"**{r['policy']} does not satisfy {name}** — a stated intention is not met")

    # A CLAIM THAT CANNOT FAIL IS A FINDING, and it belongs beside the broken ones rather than in
    # a footnote. It holds, this report counts it as a stated intention that was met, and it
    # examined nothing -- which makes the directory look BETTER checked than a directory with no
    # property module at all. That is the one way this report can actively mislead.
    for name, r in results.get("properties", {}).items():
        for claim in (r.get("claims") or {}).get("vacuous", []):
            out.append(f"**{name}: `{claim}` cannot fail** — it is already true in every state it "
                       f"ranges over, before the policy set is consulted. It holds, and it tested "
                       f"nothing")

    for name, r in results.get("derived", {}).items():
        if r.get("_failed"):
            out.append(f"**{name} could not be checked** — the checker produced no verdict")
            continue
        for rule in r.get("rules", []):
            if rule["verdict"] in ("VACUOUS", "REDUNDANT", "DEAD"):
                why = (rule.get("blame") or {}).get("terms") or []
                because = f" — because `{' && '.join(why)}`" if why else ""
                out.append(f"**{name}: {rule['verdict']} {rule['effect']} #{rule['index']}**"
                           f"{because}")
    return out


def questions_row(plan: Plan, results: dict, model_used: bool) -> str:
    """How many questions were answered, and why the rest were not. A bare 0 reads as "none"."""
    llm = results.get("llm")
    if llm is None:
        return str(len(plan.questions) if model_used else 0)
    row = f"{llm['answered']} of {len(plan.questions)}"
    if llm.get("skipped"):
        row += f" — not asked: {llm['skipped']}"
    if llm.get("failed"):
        row += " — " + "; ".join(llm["failed"])
    return row.replace("|", "\\|")


def report(plan: Plan, results: dict, findings: list[str], *, model_used: bool,
           scanned: list[str] | None = None) -> str:
    """The findings file. Written whether or not a model ran."""
    lines = [f"# Findings — `{plan.subject or plan.directory.name}`", ""]
    # THE INPUT SCAN FIRST: whether a model was shown this directory's text, and whether that text
    # held anything aimed at one, changes how every model-written word below should be read.
    if scanned:
        lines += scanned + [""]

    # A SMOKE SWEEP CANNOT ESTABLISH ABSENCE, so it must not be summarised as having found none.
    # `--smoke` explores a random sample of behaviours: a witness found that way is sound -- a
    # witness is a witness however it was reached -- but "no witness" means this walk did not
    # reach one, which is not the same claim as "there is none". VACUOUS, REDUNDANT and DEAD are
    # all claims of absence, so a smoke run never reports any of them, and a headline saying "no
    # inert rules found" would be describing a question that was never asked.
    smoke = results.get("smoke")

    if findings:
        lines += [f"**{len(findings)} thing(s) to look at.**", ""]
        lines += [f"{i}. {f}" for i, f in enumerate(findings, 1)]
    elif smoke:
        lines += [f"**Nothing to report, and that is a weaker statement than usual.** This was a",
                  f"SMOKE sweep — {smoke} random behaviours per policy set rather than an exhaustive",
                  "search — so no rule here could have been reported inert even if it were. See",
                  "the note below.", ""]
    elif plan.properties:
        lines += ["**Nothing found.** Every rule is load-bearing and every stated intention holds,",
                  "within the bounds each check reports.", ""]
    else:
        # NOT "every stated intention holds" -- there are none, so that sentence is vacuously
        # true, and a report whose headline is a vacuous truth is the exact failure this project
        # exists to catch. Say what was actually established.
        lines += ["**No inert rules found**, within the bounds each check reports. Nothing here",
                  "says the policy sets do what they were meant to do — see below.", ""]
    lines.append("")

    if smoke:
        lines += [
            f"> **This run was `--smoke {smoke}`.** Each policy set was explored as {smoke} random",
            "> behaviours instead of exhaustively, because this set's request space is the product",
            "> of its field domains and too large to exhaust. That changes what the verdicts mean:",
            ">",
            "> | | |",
            "> |---|---|",
            "> | `live` | **sound.** A witness is a witness however it was found, so the rule "
            "really does change some verdict |",
            "> | `unknown` | **not a finding.** This walk did not reach a session where the rule "
            "matters. It does not mean the rule is inert |",
            ">",
            "> **VACUOUS, REDUNDANT and DEAD cannot appear in this report at all** — each is a "
            "claim",
            "> that no session exists, and a random walk cannot establish one. To get those "
            "verdicts,",
            "> re-run without `--smoke` and expect it to take much longer.",
            ""]

    lines += ["## What was checked", "",
              "| | |", "|---|---|",
              f"| policy sets | {len(plan.policies)} |",
              f"| stated intentions (`.tla`) | {len(plan.properties)} |",
              f"| questions answered | {questions_row(plan, results, model_used)} |",
              # SAID EVERY TIME, the default included: a verdict is scoped to a reading, and one
              # that does not say which gets read as being about the deployed configuration.
              "| event-schema reading | " + (
                  f"`{results['reading']}`, the schema given" if str(results.get("reading", "")).endswith(".dwschema")
                  else "unpinned, by `--unpinned`: no pins, so a temporal condition sees every "
                       "principal's events" if results.get("reading") == "unpinned"
                  else "pinned by `callerPrincipal`, Dogwood's default") + " |", ""]

    # THE SENTENCE THAT KEEPS THIS HONEST. A clean report over a directory with no stated
    # intentions means far less than a clean report over one with them, and nothing else in this
    # file distinguishes the two.
    if not plan.properties:
        lines += [
            "> **No stated intentions were found in this directory**, so only the questions that",
            "> can be asked WITHOUT knowing intent were answered: is any rule inert, does any",
            "> edit widen. Those would pass a policy set that does the exact opposite of what its",
            "> author wanted — a rule that fires is a rule that fires, whichever way round its",
            "> condition reads. Write what the policy set is supposed to mean as a `.tla` module",
            "> beside it, and this report can check that too.", ""]

    if plan.unpaired:
        lines += ["## Modules not run", ""]
        lines += [f"- `{u['module']}` — {u['why']}" for u in results.get("unpaired", [])]
        lines.append("")

    lines += ["## Per policy set", "", "| policy set | rules | verdicts |", "|---|---|---|"]
    for name, r in results.get("derived", {}).items():
        if r.get("_failed"):
            lines.append(f"| `{name}` | — | could not be checked |")
            continue
        rules = r.get("rules", [])
        verdicts = ", ".join(sorted({rule["verdict"] for rule in rules})) or "no rules"
        lines.append(f"| `{name}` | {len(rules)} | {verdicts} |")
    lines.append("")

    if plan.properties:
        lines += ["## Stated intentions", "", "| policy set | module | |", "|---|---|---|"]
        for name, r in results.get("properties", {}).items():
            lines.append(f"| `{r['policy']}` | `{name}`"
                         f"{' (given with `--property`)' if r.get('given') else ''} | "
                         f"{'holds' if r.get('held') else '**BROKEN**'} |")
        lines.append("")

        # WHAT "HOLDS" MEANT, spelled out. Above is a verdict about a claim; here is the claim,
        # in words, with the number of states its condition actually applied to. A reader who
        # disagrees with one of these lines has found something no amount of model checking
        # would have told them, because every check below it was faithful to the wrong claim.
        lines += ["### What each of them forbids", "",
                  "Read these before the verdicts above. Each line is the only thing its claim",
                  "can catch — a claim that forbids nothing you object to passes without having",
                  "tested what you meant.", ""]
        for name, r in results.get("properties", {}).items():
            read = r.get("claims") or {}
            claims, states = read.get("claims", []), read.get("states", [])
            # How many states, or why that could not be said. A module whose state space could not
            # be read still gets its claims listed -- the `forbids` line is the useful half, and
            # silently omitting the count would read as "no states" rather than "not counted".
            lines.append(f"**`{name}`** — " + (f"{len(states)} state(s), enumerated from `Init`"
                                               if states else
                                               f"states not enumerated: {read.get('scope', '')}"))
            lines.append("")
            for c in claims:
                if not c.get("defined"):
                    lines.append(f"- `{c['name']}` — **not defined in the module**, though the "
                                 f".cfg names it")
                    continue
                applied = (f" _(its condition applies to {len(c['appliesTo'])} of "
                           f"{c['states']} states)_" if c.get("condition") else "")
                warn = " **— NOTHING IT RANGES OVER CAN BREAK IT**" if c.get("vacuous") else ""
                lines.append(f"- `{c['name']}` forbids: {c['forbids']}{applied}{warn}")
            if unchecked := (r.get("claims") or {}).get("definedButNotChecked", []):
                lines.append(f"- _defined but not named in the `.cfg`, so never checked:_ "
                             + ", ".join(f"`{u}`" for u in unchecked))
            lines.append("")

        # THE SESSION THAT BREAKS IT, in Dogwood. A counterexample is the most useful thing a model
        # checker produces and the least useful thing to print as a TLA+ variable: `gap = 960` is
        # an answer in a language the policy's author never chose. Below it is a trace they can
        # feed to `dogwood replay` themselves -- and, where the binary was available, the verdict
        # the engine already gave it.
        witnessed = [(name, r) for name, r in results.get("properties", {}).items()
                     if r.get("witness")]
        if witnessed:
            lines += ["### The session that breaks it", "",
                      "Each of these is a concrete history, in Dogwood's own trace syntax, that",
                      "the policy set decides the opposite way from the claim about it. Where a",
                      "verdict is shown it is the **Dogwood engine's**, not ours — the finding",
                      "does not rest on our reading of the language.", "",
                      "**Every file the engine needs is kept beside each finding**, so you can run",
                      "it yourself rather than take this on trust — the trace, a Cedar schema",
                      "generated from the policy set's own actions, and a copy of the policy set. Each",
                      "directory has a README and answers for itself if you move it.", ""]
            for name, r in witnessed:
                for w in r["witness"]:
                    lines.append(f"**`{name}` — {w.get('invariant', '?')}**"
                                 + (f" (`{'`, `'.join(f'{k} = {v}' for k, v in w['state'].items())}`)"
                                    if w.get("state") else ""))
                    lines += ["", w.get("sentence", ""), ""]
                    if w.get("trace"):
                        lines += ["```", w["trace"].rstrip(), "```", ""]

                    # The exact command, with the paths this run actually wrote -- not a template
                    # with placeholders to fill in. A reader who has to reconstruct the invocation
                    # is a reader who does not check the finding.
                    if w.get("command") and w.get("directory"):
                        # Relative to the report, which is what a reader has open. Both sides are
                        # resolved first: the kept path is relative to the working directory and
                        # the report's is not, so comparing them as written silently fails and
                        # prints an absolute path from somebody else's machine.
                        rel = Path(w["directory"]).resolve()
                        try:
                            rel = rel.relative_to(Path(results.get("directory", ".")).resolve())
                        except (ValueError, OSError):
                            pass
                        lines += [f"Run it yourself, from `{rel.as_posix()}`:", "",
                                  "```bash", w["command"], "```", ""]
            lines.append("")

    lines += ["---", "",
              "`traces/` holds the generated model, the configs and the raw TLC output for every",
              "run above, each with a README giving the command to re-run it. `results.json` is the",
              "same findings as data.", ""]
    return "\n".join(lines)


def ask_model(plan: Plan, results: dict, out: Path, provider: str,
              model: str | None) -> tuple[int, list[str]]:
    """Put the directory's own questions to the agent, and save the whole exchange.

    Returns how many were answered, and why each failure failed. The agent is given the questions
    and the policy paths; it runs the tools itself, which is the point -- this is the same surface
    an MCP host would use, and a transcript of it is evidence about that surface rather than about
    this script.
    """
    from agent.policy_agent import describe_failure, review

    transcript = out / "transcript.md"
    answered, failures = 0, []
    for q in plan.questions:
        # A FIRST QUESTION THAT FAILS is almost always the key or the provider, and every question
        # after it would fail the same way, each after its own retries.
        if failures and not answered:
            failures.append(f"{q.heading}: not asked, after the first question failed")
            continue
        target = plan.directory / q.policy if q.policy else (
            plan.policies[0] if plan.policies else None)
        if target is None or not target.exists():
            print(f"  skipping {q.heading!r}: names no policy set in this directory", file=sys.stderr)
            continue

        request = f"{q.text}\n\nThe policy file is {target}."
        if q.against and (plan.directory / q.against).exists():
            request += (f"\n\nThe second policy file, to compare against, is "
                        f"{plan.directory / q.against}.")

        print(f"  asking: {q.heading}", file=sys.stderr)
        try:
            review(request, project_dir=REPO, model=model, provider=provider,
                   transcript=transcript, heading=q.heading)
            answered += 1
        except (Exception, SystemExit) as e:                      # noqa: BLE001
            # One question failing must not lose the others, or the run. SystemExit included:
            # `build_model` raises it for a missing key or region, and uncaught it ended the audit
            # after every check had run and before any of them was written up.
            why = describe_failure(e)
            print(f"    failed: {why}", file=sys.stderr)
            failures.append(f"{q.heading}: {why}")
    return answered, failures


def scan_note(scan: screen.Report, *, withheld: bool, overridden: bool) -> dict[str, list[str]]:
    """What the input scan means for this report, for findings.md and for findings.html."""
    s = scan.summary()
    if withheld:
        md = ["> **The input scan found high-severity text in this directory's inputs, so the "
              "model's questions were NOT asked.** The checks below ran in full: they are "
              "deterministic and not at risk from text aimed at a model. Read the findings with "
              "`anchor scan`, and if they are benign run again with `--allow-flagged-input`.",
              ">", f"> {s}"]
        html = ["The model's questions were not asked, because of the high-severity findings "
                "below. The checks ran in full."]
    elif overridden:
        md = ["> **The input scan flagged this directory's inputs, and the model was asked its "
              "questions anyway (`--allow-flagged-input`).** Everything a model wrote below was "
              "written by one that read that text.", ">", f"> {s}"]
        html = ["The model was asked its questions anyway, under --allow-flagged-input: "
                "everything it wrote was written by one that read the text below."]
    elif scan.high or scan.medium:
        md = [f"**Input scan.** {s} -- no model read them, so nothing was withheld; "
              f"`anchor scan` lists what was found."]
        html = []
    else:
        md = [f"**Input scan.** {s}."]
        html = []
    return {"md": md, "html": html}


def refuse(explicit: list[str], problems: list[str], warnings: list[str] = ()) -> int:
    """An LLM asked for by name that cannot be had: said, and stopped, before anything runs."""
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    named = " and ".join(explicit)
    print(f"\nnot run: {named} {'asks' if len(explicit) == 1 else 'ask'} for LLM calls, and they "
          f"cannot be made as things stand. Fix the above, or leave out {named} to run every check "
          f"and skip the questions with a warning.", file=sys.stderr)
    return 3


def announce(plan: Plan, target: Path, out: Path, args: argparse.Namespace, ready, skipped: str) -> str:
    """What this audit is about to do, from the options it was given. Said before the first TLC
    run, because the first result can be minutes away."""
    def names(modules: list[str]) -> str:
        return ", ".join(modules[:6]) + (f", and {len(modules) - 6} more" if len(modules) > 6 else "")

    pad = " " * 20
    what = "one policy set" if plan.subject else f"{len(plan.policies)} policy set(s)"
    bound = (f"a random walk of {args.smoke} behaviours each (--smoke): finds live rules, never "
             f"VACUOUS, REDUNDANT or DEAD" if args.smoke else
             f"exhaustive, sessions of up to {args.attempts or 3} attempts")
    reading = (f"the event schema {args.event_schema.name}" if args.event_schema else
               "unpinned: every principal's events" if args.reading == "unpinned" else
               "callerPrincipal pinned, Dogwood's default" if args.reading else
               "callerPrincipal pinned, Dogwood's default (--unpinned or --event-schema to change)")
    lines = [f"Audit of {target} ({what}):",
             f"  1. rule by rule   {what}, one or two TLC runs per rule",
             f"{pad}{bound}",
             f"{pad}reading: {reading}"]

    if plan.properties:
        given = {m.resolve() for m in plan.given}
        lines.append(f"  2. modules        {len(plan.properties)} property module(s): " + names(
            [m.name + (" (--property)" if m.resolve() in given else "") for m, _ in plan.properties]))
    else:
        lines.append("  2. modules        no property module found")
    if plan.unpaired:
        lines.append(f"{pad}{len(plan.unpaired)} more cannot run, and the report says why: "
                     + names([m.name for m, _ in plan.unpaired]))

    if ready is not None:
        lines += [f"  3. questions      {len(plan.questions)} from questions.md, asked of {ready.model} "
                  f"via {ready.provider}",
                  f"{pad}model: {ready.model_source}",
                  f"{pad}credentials: {ready.source}. These are live LLM calls"
                  + ("; a one-token test request was answered just now" if ready.tested else "")]
    else:
        count = f"{len(plan.questions)} in questions.md, " if plan.questions else ""
        lines.append(f"  3. questions      {count}not asked: {skipped}")

    lines += [f"  report            {out}",
              f"{pad}findings.md, findings.html, results.json, traces/",
              "Each TLC run is announced as it starts; a large policy set takes minutes."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", type=Path,
                    help="a directory of .dw policy sets, or one .dw policy set to audit on its own")
    ap.add_argument("--output-dir", type=Path, default=None,
                    help="where to write findings.md, findings.html, results.json and traces/ "
                         "(default: the directory itself, or <policy-set>-findings/ beside a "
                         "single policy set, so it never overwrites the directory's report)")
    ap.add_argument("--property", type=Path, metavar="FILE.tla",
                    help="one policy set only: a property module to check as well as the ones "
                         "whose header names it -- kept elsewhere, not yet given the header, or "
                         "written for several policy sets. Needs its .cfg beside it")
    ap.add_argument("--list", action="store_true",
                    help="print the property modules and questions an audit would use, and stop. "
                         "Reads headers and questions.md; runs nothing")
    ap.add_argument("--no-llm", action="store_true",
                    help="run the checks and write the report without asking an LLM anything. "
                         "Most of the value, none of the cost, and the part that belongs in CI")
    ap.add_argument("--provider", type=str, default=None, choices=("auto", "bedrock", "gemini"),
                    help="which service's LLM answers questions.md. auto picks gemini when a Gemini "
                         "API key is configured, bedrock otherwise. Credentials come from the "
                         "environment first, then the settings file (see --config). Given at all -- "
                         "`--provider auto` included -- it makes the LLM required and tests it first")
    ap.add_argument("--llm", type=str, default=None, metavar="MODEL-ID",
                    help="which model the provider runs. Default: the provider's Model setting "
                         "(Gemini:Model or Bedrock:Model), then gemini-2.5-flash, or the Strands "
                         "SDK's own for bedrock. Not needed to use an LLM: one is asked whenever "
                         "there is a questions.md, unless --no-llm")
    ap.add_argument("--config", type=Path, default=None, metavar="APPSETTINGS.JSON",
                    help="the settings file holding the LLM's API key, model and provider settings. "
                         "Default: $ANCHOR_APPSETTINGS, else src/agent/appsettings.json, else one "
                         "at the Anchor root. A path that is not there is refused")
    ap.add_argument("--attempts", type=int, default=None, help="session length bound")
    ap.add_argument("--smoke", type=int, nargs="?", const=1000, default=None, metavar="N",
                    help="explore each policy set as a random walk of N behaviours (default 1000) "
                         "instead of exhaustively -- for a set whose request space is too big to "
                         "exhaust. Reports `live` or `unknown` and NEVER vacuous, redundant or "
                         "dead: those are claims of absence, and a random walk cannot establish "
                         "one. The report says so")
    ap.add_argument("--max-fields", type=int, default=None, metavar="N",
                    help="refuse a policy set reading more than N input/output fields (default 4). "
                         "The request space is the product of their domains, so raising this "
                         "trades runtime for reach rather than soundness")
    reading = ap.add_mutually_exclusive_group()
    reading.add_argument("--pinned", action="store_const", const="pinned", dest="reading",
                         help="Dogwood's own default reading, and Anchor's, stated explicitly: "
                              "callerPrincipal pinned, so a temporal condition sees only the "
                              "requesting principal's events")
    reading.add_argument("--event-schema", type=Path, metavar="FILE.dwschema",
                         help="the .dwschema every policy set here is deployed under")
    reading.add_argument("--unpinned", action="store_const", const="unpinned", dest="reading",
                         help="no pins, so a temporal condition sees every principal's events in "
                              "the session. For a deployment whose event schema has no universal "
                              "pin")
    ap.add_argument("--allow-flagged-input", action="store_true",
                    help="ask the LLM its questions even when the input scan found "
                         "high-severity text. For findings you have read and judged benign; the "
                         "report records that it was used")
    args = ap.parse_args()

    # AN LLM THAT WAS ASKED FOR, and one that merely would have been used. With none of these the
    # LLM is the optional part of an audit: if it cannot be reached the questions are skipped with
    # a warning and every check still runs. Naming any of them is a request for model calls, and
    # one that cannot be met stops the run before its first TLC run rather than after its last.
    explicit = [name for name, given in (("--llm", args.llm), ("--provider", args.provider),
                                         ("--config", args.config)) if given]
    if explicit and args.no_llm:
        ap.error(f"{explicit[0]} asks for an LLM and --no-llm says not to; pass one or the other")

    # Before any check runs, so a mistyped path fails now rather than after minutes of TLC.
    if args.config is not None:
        from agent.policy_agent import use_appsettings                    # noqa: PLC0415
        use_appsettings(args.config)

    # A DIRECTORY, OR ONE POLICY SET IN IT. The single set is the directory narrowed to that
    # file, so the two produce the same report and there is one audit rather than two.
    target = args.target
    if target.is_file() and target.suffix.lower() == ".dw":
        directory = target.parent
        plan = narrow(discover(directory), target)
        default_out = directory / f"{target.stem}-findings"
    elif target.is_dir():
        directory = target
        plan = discover(directory)
        default_out = directory
    else:
        print(f"{target} is neither a directory nor a .dw policy set", file=sys.stderr)
        return 3

    # ADDED, NOT SUBSTITUTED: "full" is everything, and an audit that dropped the discovered
    # modules because one was named would be the surprising kind of override. Checking only the
    # named one is what a plain `check --property` is for.
    if args.property is not None:
        if not plan.subject:
            ap.error("--property names one policy set's module; with a directory, name the policy "
                     "set in the module's header instead")
        module = args.property.resolve()
        if not module.is_file() or not module.with_suffix(".cfg").is_file():
            ap.error(f"--property {args.property}: needs the .tla and a .cfg beside it naming its "
                     f"invariants")
        paired = {m.resolve(): m for m, _ in plan.properties}
        if module not in paired:
            # Two modules of one name would share a traces/ folder and a row in the report.
            if any(m.name == module.name for m in paired):
                ap.error(f"--property {module.name}: a module of that name is already found by "
                         f"header here; rename one of them")
            plan.properties.append((module, target))
            plan.given.append(module)

    if args.list:
        if (said := available(plan)):
            print(said)
        return 0

    if not plan.policies:
        print(f"no .dw policy sets in {directory}", file=sys.stderr)
        return 3

    out = args.output_dir or default_out

    # THE INPUT SCAN, BEFORE ANYTHING READS THE INPUTS. The checks run in full whatever it finds:
    # the parser, TLC and Dogwood are deterministic and not at risk from text aimed at a model.
    # What a high finding withholds is the MODEL -- the one reader here that would follow it.
    # Only what this audit reads: the whole directory for a directory, and for one policy set
    # just it, its modules and their .cfg, the questions and the schema. Another set's text
    # must not withhold the LLM from this one.
    if plan.subject:
        # A module given with --property is read like any other, wherever it lives.
        reads = [target, *[f for m, _ in plan.properties for f in (m, m.with_suffix(".cfg"))],
                 *([directory / "questions.md"] if plan.questions else []),
                 *([args.event_schema] if args.event_schema else [])]
    else:
        reads = [directory, *([args.event_schema] if args.event_schema else [])]
    scan = screen.scan(reads, relative_to=directory)
    if scan.high or scan.medium:
        print(screen.render(scan, census=False) + "\n", file=sys.stderr)
    withheld = (bool(scan.high) and not args.no_llm and bool(plan.questions)
                and not args.allow_flagged_input)

    # EVERYTHING THAT CAN BE KNOWN BEFORE THE RUN, said before it: whether the questions will be
    # asked, and if not, why. Whether a key WORKS cannot be known without a live call, so a
    # rejected one still surfaces at the first question.
    ready, skipped, warnings = None, "", []
    if args.no_llm:
        skipped = "--no-llm"
    elif not plan.questions:
        skipped = ("no questions.md" if not (directory / "questions.md").exists() else
                   f"no question in questions.md names {plan.subject}" if plan.subject else
                   "questions.md holds no questions")
        if explicit:
            warnings.append(f"{explicit[0]} was given, but there is nothing to ask an LLM: {skipped}.")
    elif withheld:
        skipped = "the input scan found high-severity text an LLM would read"
        if explicit:
            return refuse(explicit, [f"the input scan above found high-severity text the LLM would "
                                     f"read. Read it with `anchor scan`; if it is benign, add "
                                     f"--allow-flagged-input."])
        warnings.append("the checks run in full, but the questions are NOT asked: the input scan "
                        "above found high-severity text an LLM would read. If it is benign, run "
                        "again with --allow-flagged-input.")
    else:
        from agent.policy_agent import probe, readiness                    # noqa: PLC0415
        ready = readiness(args.provider or "auto", args.llm)
        warnings += ready.warnings
        if ready.problems:
            if explicit:
                return refuse(explicit, ready.problems)
        elif explicit:
            # ASKED FOR BY NAME, SO PROVEN BEFORE THE RUN: one request of one output token, which
            # is the only way to learn that the key works, the model id exists and the account may
            # call it -- before minutes of TLC rather than after. Unnamed, a failure at the first
            # question is a warning, and nothing is spent finding it out early.
            print(f"testing {ready.model} via {ready.provider} with a one-token request ...",
                  file=sys.stderr, flush=True)
            if (problem := probe(ready.provider, args.llm)):
                # The settings warning may be the reason: a Model or Region that did not apply.
                return refuse(explicit, [problem], ready.warnings)
            ready.tested = True
        if ready.problems:
            skipped = f"no LLM is configured ({ready.problems[0]})"
            warnings += ready.problems + [
                f"the {len(plan.questions)} question(s) in questions.md will be skipped, and the "
                f"report says why; every check still runs. --no-llm says this was intended."]
    if not plan.properties:
        about = plan.subject or "these policy sets"
        warnings.append(f"no property module states what {about} should mean, so only the "
                        f"rule-by-rule checks run. They find rules that do nothing, not rules that "
                        f"do the opposite of what was meant. To check that, write the meaning as a "
                        f".tla module beside it; see "
                        f"src/Anchor.MCPServer/knowledge/writing-a-property-module.md.")

    asking = ready is not None and not ready.problems
    print(announce(plan, target, out, args, ready if asking else None, skipped), file=sys.stderr)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print("", file=sys.stderr, flush=True)

    out.mkdir(parents=True, exist_ok=True)
    results = check_all(plan, out, attempts=args.attempts, smoke=args.smoke,
                        max_fields=args.max_fields, reading=args.reading,
                        event_schema=args.event_schema)
    results["inputScan"] = scan.as_dict() | {"modelWithheld": withheld}
    findings = findings_of(results)

    answered, failed = 0, []
    if asking:
        print(f"\nasking {len(plan.questions)} question(s) of {ready.model} ({ready.provider}); "
              f"these are live LLM calls", file=sys.stderr, flush=True)
        answered, failed = ask_model(plan, results, out, ready.provider, args.llm)
    results["llm"] = {"provider": ready.provider if asking else None,
                      "model": ready.model if asking else None,
                      "answered": answered, "skipped": skipped, "failed": failed}

    note = scan_note(scan, withheld=withheld, overridden=bool(scan.high) and asking)
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    (out / "findings.md").write_text(
        report(plan, results, findings, model_used=bool(answered), scanned=note["md"]),
        encoding="utf-8")

    # THE PICTURE, beside the prose. Never allowed to fail the audit: every check has already run
    # and been written up, and a report that could not be drawn is a missing convenience, not a
    # missing finding -- so it is said, not raised.
    try:
        from checker.timeline import write_report                      # noqa: PLC0415
        page = write_report(out, inputs=target, findings=findings, notes=note["html"],
                            scanned=scan)
        print(f"wrote {page}", file=sys.stderr)
    except Exception as e:                                              # noqa: BLE001
        print(f"findings.html was not written ({type(e).__name__}: {e}); findings.md is complete "
              f"without it", file=sys.stderr)

    print(f"\n{len(findings)} finding(s); wrote {out / 'findings.md'}", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)

    if failed:
        print(f"\n{'error' if explicit else 'warning'}: {len(failed)} of {len(plan.questions)} "
              f"question(s) were not answered; the checks and the report are complete.",
              file=sys.stderr)
        # Asked for, and not delivered: 3, "could not do what was asked", even though the report
        # is written -- a script that passed --llm must not read the findings exit as success.
        if explicit:
            return 3

    # Non-zero when there is something to look at, so this can gate a pipeline. Distinct from 3,
    # which means the run could not happen at all -- the same contract the single-policy run
    # uses, because `anchor check` now takes either shape and one number must mean one thing.
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
