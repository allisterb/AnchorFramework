"""Draft a property module from a stated intention -- and refuse to keep one that says nothing.

    python src/agent/author.py examples/aws1/07-trust-decay.dw \\
        --intent "After 15 minutes without advisor interaction, the agent loses write access."

THE HAZARD THIS IS BUILT AROUND, stated before the feature: a property an agent derives from the
POLICY is a restatement of the policy. Checking a policy against its own restatement always passes
and establishes nothing. It is a documented failure in agentic verification (measured by Lahiri, arXiv:2608.21516): asked to
produce both an artifact and its specification, a model can find that a trivial specification is
the cheapest way to pass. `ensures TRUE` holds of everything.

So two things, and neither is optional:

    THE INTENT COMES FROM SOMEWHERE ELSE.  `--intent` is prose the policy did not write: a
                                           requirement, a comment, an article's sentence, what the
                                           person actually asked for. Autoformalising a REQUIREMENT
                                           is a different act from summarising a rule, and only the
                                           first can disagree with the policy.

    THE DRAFT MUST DISCRIMINATE.           A property is kept only if it either fails on the policy
                                           as written -- in which case it has already shown it can
                                           tell one policy from another -- or, holding, catches at
                                           least one MUTANT: a version of the policy broken in a
                                           small way. A property true of the policy and of every
                                           broken version of it is not constraining anything.

WHAT COMES OUT IS A DRAFT. It is a formal statement of somebody's prose, written by a model, and
whether it captures what they meant is exactly the question no tool answers. Findings against an
agent-authored property are weaker evidence than findings against one a person wrote, and anything
reporting them should say which it has.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from agent import invoke                               # noqa: E402

CHECKER = invoke.CHECKER          # kept importable; the path now lives in `invoke`

WEAK_PROPERTY = 4   # properties.py: holds, but catches no mutant

INVARIANT_LINE = re.compile(r"^INVARIANT\s+(\w+)", re.MULTILINE)


@dataclass
class Draft:
    """One attempt at a property module, and what the checker made of it."""

    number: int
    module: str
    config: str
    accepted: bool = False
    complaints: list[str] = field(default_factory=list)
    holds: bool | None = None
    caught: int | None = None
    output: str = ""

    def feedback(self) -> str:
        return "\n".join(f"- {c}" for c in self.complaints)


@dataclass
class AuthorRun:
    drafts: list[Draft] = field(default_factory=list)
    accepted: Draft | None = None


def describe(policy: Path, event_schema: Path | None = None,
             max_fields: int | None = None) -> dict:
    """The vocabulary a property module may name, from the checker itself.

    NOT GUESSED AND NOT ASKED OF THE MODEL. The actions, field names and value domains come from
    the policy's own text, and a module naming anything else does not compile. Handing the model
    the real vocabulary is the difference between drafting and inventing.
    """
    args = [str(policy), "--describe"]
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]
    if max_fields is not None:
        args += ["--max-fields", str(max_fields)]
    proc = invoke.checker(args, timeout=300)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_failed": True, "_why": (proc.stderr or proc.stdout).strip()[-1200:]}


def compiles(policy: Path, module: Path, *, event_schema: Path | None = None,
             max_fields: int | None = None, timeout: int = 300) -> tuple[bool, str]:
    """Does this module parse and resolve? SANY, about a second, against minutes for `score`.

    NEEDS THE POLICY, and that is not incidental: a property module EXTENDS `PolicyUnderTest`,
    which is generated from the policy, so "does it compile" is only answerable against a
    particular one. Parsing the module alone reports the whole vocabulary missing.

    The output is the drafter's feedback when this fails, so it is returned whole -- SANY names the
    line, the column and the token, and a complaint without those is one no next round can act on.
    """
    args = [str(policy), "--property", str(module), "--parse"]
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]
    if max_fields is not None:
        args += ["--max-fields", str(max_fields)]
    proc = invoke.checker(args, timeout=timeout)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def decides(policy: Path, module: Path, *, event_schema: Path | None = None,
            max_fields: int | None = None, timeout: int = 900) -> tuple[str, str]:
    """Does the policy's answer VARY over the states this module ranges over? Seconds, two TLC runs.

    THE GATE BETWEEN `preflight` AND `score`, and it earns its place: preflight asks whether a
    claim's CONDITION can be satisfied, and mutation scoring asks whether the property notices the
    policy breaking. Neither asks whether the policy's DECISION ever changes across the states the
    property names -- and when it does not, every claim about a refusal holds without testing
    anything. Mutation catches it eventually, at one TLC run per mutant, and reports the symptom
    ("it survived every mutant") rather than the cause.

    Returns (verdict, what the checker said). `skipped` when no decision term could be found, and
    the caller must treat that as "learned nothing" rather than as a pass or a failure.
    """
    args = [str(policy), "--property", str(module),
            "--decision-probe"]
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]
    if max_fields is not None:
        args += ["--max-fields", str(max_fields)]
    proc = invoke.checker(args, timeout=timeout)
    out = (proc.stdout + proc.stderr).strip()

    m = re.search(r"decision over this module's states: (\w+)", out)
    return (m.group(1).lower() if m else "skipped"), out


def score(policy: Path, module: Path, *, event_schema: Path | None = None,
          max_fields: int | None = None, mutants: int = 8, timeout: int = 3600) -> dict:
    """Check a property AND ask whether it would notice the policy breaking.

    One invocation, because the two answers belong together: "it holds" is only reassuring
    alongside "and it would not have held of something broken".
    """
    args = [str(policy), "--property", str(module),
            "--mutation-score", "--mutants", str(mutants)]
    if event_schema is not None:
        args += ["--event-schema", str(event_schema)]
    if max_fields is not None:
        args += ["--max-fields", str(max_fields)]
    proc = invoke.checker(args, timeout=timeout)
    out = proc.stdout + proc.stderr

    caught = None
    if (m := re.search(r"^\s*(\d+) of (\d+) caught\.", out, re.MULTILINE)):
        caught = int(m.group(1))

    # 4 is "holds, but caught no mutant" -- it HOLDS, and `assess` below is what rejects it.
    # Reading 4 as a failure would have `assess` conclude the property discriminates, which is the
    # exact opposite of what exit 4 means, and would wave through the one draft the gate exists to
    # stop.
    return {"holds": proc.returncode in (0, WEAK_PROPERTY), "exitCode": proc.returncode,
            "caught": caught, "output": out.strip(),
            # A TLA+ module that will not parse is not a verdict about the policy. Distinguished
            # from a property that ran and failed, because the two need opposite responses.
            #
            # Exit 2 is the checker saying so itself -- it runs SANY before TLC and returns "no
            # verdict" rather than a violation. The string scan stays as well: it predates that
            # and it costs nothing, and a gate that relies on exactly one signal for "this was
            # never checked" is a gate one refactor away from waving a draft through.
            "ran": proc.returncode != 2 and not any(
                n in out for n in ("Could not parse module", "AbortException",
                                   "Parsing or semantic analysis failed"))}


def preflight(module: str, config: str, name: str, vocab: dict | None = None) -> list[str]:
    """What is wrong with this draft that can be seen WITHOUT running anything.

    The gate below costs one TLC run for the property plus one per mutant -- minutes, for a draft
    that a reader can reject in a glance. Two of the ways a drafted property comes back useless are
    decidable from its own text: a `.cfg` naming an invariant the module never defines, and a claim
    whose truth in every state it ranges over is already settled by the module's own arithmetic.

    Both are hard rejections rather than warnings, because both are unambiguous -- and because the
    complaint they produce is more specific than the one mutation scoring would eventually give.
    "Nothing you are ranging over can break this" names the defect; "it survived every mutant"
    describes a symptom of it.
    """
    from checker.explain import Module, explain            # noqa: PLC0415

    x = explain(Module(module, config, name))
    complaints: list[str] = []

    for claim in x.claims:
        if not claim.defined:
            complaints.append(f"the .cfg names INVARIANT {claim.name}, which the module does not "
                              f"define. TLC stops with an error rather than checking anything")
        elif claim.vacuous:
            complaints.append(
                f"{claim.name} cannot fail. It is already true in all "
                f"{claim.total} state(s) it ranges over before the policy is consulted at all"
                + (f", because `{claim.condition}` is false in every one of them" if claim.condition
                   and not claim.applies else "")
                + f". It would forbid: {claim.forbids} -- and no state it examines is one. Range "
                  f"over values that can make the condition true, and state the claim in terms of "
                  f"what the policy DECIDES")

    complaints += tagged_orderings(module)
    if vocab:
        complaints += misplaced_fields(module, vocab)
    return complaints


# An ordering operator beside a tag constructor: `x <= Num(2500)`, `Num(1) > 0`. Certain to fail,
# because `Num(...)` is a record and `<=` wants integers -- and an earlier version of the property
# module article TAUGHT `input.amount <= Num(2500)` as the right form. The lookarounds keep out
# `<<`, `>>`, `->`, `|->`, `<-`, `=>` and `<=>`.
ORDERING = r"(?<![<=>\-|])(?:<=|>=|=<|<|>|\\leq|\\geq)(?![<=>\-])"
TAG_CALL = r"\b(?:Num|Str|Bool|Addr)\([^()]*\)"
TAGGED_ORDERING = re.compile(rf"{ORDERING}\s*{TAG_CALL}|{TAG_CALL}\s*{ORDERING}")


def code_only(module: str) -> str:
    """`module` with comments and string literals blanked, line and column positions kept."""
    out, i, n, depth = list(module), 0, len(module), 0
    while i < n:
        two = module[i:i + 2]
        if depth:
            if two == "(*":
                depth += 1
            elif two == "*)":
                depth -= 1
                out[i] = out[i + 1] = " "
                i += 2
                continue
            if module[i] != "\n":
                out[i] = " "
            i += 1
        elif two == "(*":
            depth = 1
            out[i] = out[i + 1] = " "
            i += 2
        elif two == "\\*":
            while i < n and module[i] != "\n":
                out[i] = " "
                i += 1
        elif module[i] == '"':
            j = i + 1
            while j < n and module[j] not in '"\n':
                j += 2 if module[j] == "\\" else 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            i = j + 1
        else:
            i += 1
    return "".join(out)


def tagged_orderings(module: str) -> list[str]:
    """One complaint per ordering of a tagged value the text makes. Certain, so a rejection."""
    code = code_only(module)
    complaints = []
    for m in TAGGED_ORDERING.finditer(code):
        line = code.count("\n", 0, m.start()) + 1
        complaints.append(
            f"line {line}: `{m.group(0).strip()}` orders a TAGGED value. `Num(...)` is a record, not "
            f"a number, so `<`, `<=`, `>` and `>=` on it fail at run time with \"The first argument "
            f"of <= should be an integer\". Compare the number inside instead: `x.v <= 2500`. "
            f"(`=` and `#` do take two tagged values: `s = Str(\"a1\")`.)")
    return complaints


def split_top(text: str) -> list[str]:
    """`text` split at commas that are not inside (), [], {} or << >>."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "<<":
            depth += 1
            i += 2
            continue
        if two == ">>":
            depth -= 1
            i += 2
            continue
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts]


def call_args(code: str, open_paren: int) -> tuple[str, int] | None:
    """The text between the parenthesis at `open_paren` and its match, and the match's index."""
    depth = 0
    for i in range(open_paren, len(code)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return code[open_paren + 1:i], i
    return None


DEFINITION = re.compile(r"^([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*==", re.MULTILINE)


def record_fields(arg: str, defs: dict[str, str]) -> set[str] | None:
    """The field names of a record argument, or None when it is not one this can read.

    A literal `[a |-> ..., b |-> ...]`, `NoFields`, or a name defined as one -- `Done ==` or
    `Doc(d) ==` -- which is how drafts usually build them. Anything else is skipped, not guessed.
    """
    arg = arg.strip()
    if arg == "NoFields":
        return set()
    name = re.fullmatch(r"([A-Za-z_]\w*)(?:\(.*\))?", arg, re.DOTALL)
    if name and name.group(1) in defs:
        arg = defs[name.group(1)].strip()
    if not (arg.startswith("[") and arg.endswith("]")):
        return None
    fields = set()
    for item in split_top(arg[1:-1]):
        if "|->" not in item:
            return None                    # a function or a set of records, not a record literal
        fields.add(item.split("|->", 1)[0].strip())
    return fields


def misplaced_fields(module: str, vocab: dict) -> list[str]:
    """Values put in the half of an event the policy never reads them from.

    The vocabulary says which field names the policy reads from an event's `input` and which from
    its `output`. A value the policy reads only as an input, placed only in an event's output, can
    match no rule. One recorded draft did exactly that -- `profile_id` in a lookup's output, where
    the policy read the lookup's input -- and passed every gate while testing nothing.

    Deliberately narrow, so it never fires on a good module: a name the policy reads from both
    halves, a value it reads from neither (`result` on a response, say), or an event that also
    carries the value where the policy reads it, is left alone.
    """
    reads_in = {f["name"] for f in vocab.get("inputFields") or []}
    reads_out = {f["name"] for f in vocab.get("outputFields") or []}
    code = code_only(module)
    defs = {}
    starts = [m for m in DEFINITION.finditer(code)]
    for here, nxt in zip(starts, starts[1:] + [None]):
        defs[here.group(1)] = code[here.end():nxt.start() if nxt else len(code)].split("====")[0]

    complaints = []
    for m in re.finditer(r"\bEv\s*\(", code):
        found = call_args(code, m.end() - 1)
        if not found:
            continue
        args = split_top(found[0])
        if len(args) != 5:
            continue
        given_in, given_out = record_fields(args[2], defs), record_fields(args[3], defs)
        if given_in is None or given_out is None:
            continue
        line = code.count("\n", 0, m.start()) + 1
        for field_name in sorted(given_out - reads_out - given_in):
            if field_name in reads_in:
                complaints.append(
                    f"line {line}: `{field_name}` is in this event's OUTPUT record, but the policy "
                    f"reads `{field_name}` only from an event's INPUT, so no rule can see it there. "
                    f"Put it in the input record, Ev's third argument.")
        for field_name in sorted(given_in - reads_in - given_out):
            if field_name in reads_out:
                complaints.append(
                    f"line {line}: `{field_name}` is in this event's INPUT record, but the policy "
                    f"reads `{field_name}` only from an event's OUTPUT, so no rule can see it there. "
                    f"Put it in the output record, Ev's fourth argument.")
    return complaints


def refusal_only(module: str, config: str, name: str) -> str | None:
    """A WARNING when every claim says the policy must refuse, or None. Never a rejection.

    No mutation that REMOVES a permission can break such a module, which is half of what mutation
    scoring tries. Of 36 recorded drafts, 19 were refusal-only and 12 of those died at scoring (63%),
    against 4 of the 12 with claims both ways (33%). But 2 refusal-only drafts passed, and a pure
    prohibition is a real kind of requirement, so this advises and does not reject.

    Read through the explainer, which says what each claim forbids: a refusal claim forbids "the
    policy GRANTS it", an allowing one "the policy REFUSES it". Claims it cannot read count as
    neither, so an unreadable module is never warned about on a guess.
    """
    from checker.explain import Module, explain              # noqa: PLC0415

    claims = [c for c in explain(Module(module, config, name)).claims if c.checked and c.defined]
    refusing = [c.name for c in claims if "the policy GRANTS it" in c.forbids]
    allowing = [c.name for c in claims if "the policy REFUSES it" in c.forbids]
    if not refusing or allowing:
        return None
    return ("WARNING, not a rejection: every claim here says the policy must REFUSE ("
            + ", ".join(f"`{n}`" for n in refusing) + "). No mutation that removes a permission can "
            "break a module like this, and most recorded drafts that looked like this were rejected "
            "at mutation scoring. If the requirement allows anything at all, add one claim that a "
            "specific, fully compliant session -- every prerequisite present -- is ALLOWED. Keep it "
            "to that session: 'X requires Y' means 'without Y, refused', not 'with Y, always "
            "allowed'.")


def diagnose(output: str) -> str | None:
    """The specific mistake a TLC run-time error points to, or None when it is not one of these.

    TLC's messages are precise about WHAT failed and say nothing about why. Each mistake below has
    its own signature, read off real runs; `[k |->` after the message is what marks a tagged value.
    """
    if re.search(r"argument of \S+ should be an integer, but instead it is:\s*\[k \|->", output):
        return ("You applied an ordering operator (<, <=, >, >=) to a TAGGED value. `Num(...)` is a "
                "record, not a number, so `x <= 22` and `x <= Num(22)` both fail. Compare the "
                "number inside: `x.v <= 22`.")
    # Two shapes, depending on which side is tagged: "equality of record: [k |-> ...] with
    # non-record", or "equality of string "a" with non-string: [k |-> ...]".
    if re.search(r"Attempted to check equality of record:\s*\[k \|->|with non-\w+:\s*\[k \|->",
                 output):
        return ("You compared a TAGGED value with a plain one using `=` or `#`. Tag both sides "
                "(`s = Str(\"a1\")`, `n = Num(22)`), or compare the insides (`s.v = \"a1\"`).")
    if re.search(r"Attempted to check equality of integer \S+ with non-integer:\s*(?:TRUE|FALSE)",
                 output):
        return ("This is the known `Init`-domain pattern: a VARIABLE ranging over TAGGED values. "
                "Let variables hold PLAIN values (`verified \\in {TRUE, FALSE}`) and tag them where "
                "they go into an event (`[verified |-> Bool(verified)]`).")
    return None


def assess(result: dict, config: str) -> list[str]:
    """Why this draft is not acceptable yet. Empty means it is."""
    complaints: list[str] = []

    if not result.get("ran"):
        # The tail, because the diagnostic is at the TOP -- SANY names the line and the token, and
        # what follows is a residual stack and the checker's own explanation. Both halves are kept
        # so a drafter gets the location it needs to fix and the reason it was not scored.
        out = result.get("output", "").splitlines()
        start = next((i for i, line in enumerate(out)
                      if "DOES NOT COMPILE" in line or "DID NOT EVALUATE" in line), None)
        said = out[start:start + 14] if start is not None else out[-14:]

        # WHICH OF THE TWO IT WAS, because they want opposite responses and this said "did not
        # compile" for both. A module that will not PARSE is a syntax error the drafter can be
        # pointed at; one that compiles and then dies evaluating is almost always the tagging
        # discipline -- `x = 1` against a `Num(1)` -- and is a different piece of advice.
        #
        # It mattered beyond wording. `hitl` reads this complaint to decide what to ask a PERSON,
        # mapped "did not compile" to "the draft was not well-formed", and asked somebody to state
        # their requirement again -- for a fault in the drafter's TLA+ that no rephrasing of a
        # requirement could touch.
        evaluated = any("DID NOT EVALUATE" in line for line in out)
        complaints.append(
            ("the module compiled but could not be evaluated, so nothing was checked:\n"
             if evaluated else "the module did not compile, so nothing was checked:\n")
            + "\n".join(said))
        return complaints

    if not INVARIANT_LINE.search(config):
        complaints.append("the .cfg names no INVARIANT, so nothing was checked. "
                          "List every claim you want checked.")
        return complaints

    # THE ADVERSARIAL GATE. A property that holds and catches nothing is true and empty.
    if result.get("holds") and result.get("caught") == 0:
        complaints.append(
            "the property HOLDS, but it also holds of every broken version of this policy that "
            "was tried -- rules deleted, permits turned into forbids, conditions dropped. So it "
            "is not constraining this policy at all. It is probably ranging over requests the "
            "policy never sees, or asserting something trivially true. State the claim about "
            "concrete actions and values the policy actually names.\n\n"
            # THE COMMONEST REASON, and it is a property of the MUTANTS rather than of any
            # particular draft, so it can be said without inspecting one. Every kind of damage
            # here removes or narrows a permission: a rule deleted, a permit typed as a forbid, a
            # condition dropped so a forbid matches more. A policy that refuses MORE still refuses
            # everything a refusal-only property said must be refused -- so such a property
            # survives all of them, however carefully it names its values.
            #
            # Three live sessions were lost to this before it was said out loud. The property that
            # eventually passed differed from the ones that did not by exactly one claim: a
            # positive one.
            "IF EVERY CLAIM YOU WROTE SAYS SOMETHING MUST BE REFUSED, THAT IS WHY. Every mutation "
            "tried removes or narrows a permission, and a policy that refuses more still refuses "
            "everything you said must be refused. Add at least one claim saying what the policy "
            "MUST ALLOW -- the request that has met every condition and has to go through. That "
            "is the claim a deleted or inverted permit breaks.")

    return complaints


def author(policy: Path, intent: str, propose, *, rounds: int = 3,
           event_schema: Path | None = None, mutants: int = 8,
           out_dir: Path | None = None, module_name: str = "Intent",
           on_draft=None) -> AuthorRun:
    """Draft a property module for `intent`, and keep it only if it discriminates.

    `propose(vocabulary, intent, feedback) -> (module_text, config_text)`. Injected, so the loop
    and its gate are testable without a model -- the gate is the part that matters and the part
    that would rot silently.
    """
    vocab = describe(policy, event_schema)
    # The name the module must carry, because this loop is what chooses the file name and TLA+
    # requires the two to agree. Carried in the vocabulary so an injected proposer sees it too.
    vocab["requiredModuleName"] = module_name
    run = AuthorRun()
    feedback = ""

    out = out_dir or policy.parent
    out.mkdir(parents=True, exist_ok=True)
    module_path = out / f"{module_name}.tla"
    config_path = out / f"{module_name}.cfg"
    existing = (module_path.read_text(encoding="utf-8") if module_path.exists() else None,
                config_path.read_text(encoding="utf-8") if config_path.exists() else None)

    try:
        for n in range(1, rounds + 1):
            module, config = propose(vocab, intent, feedback)
            module_path.write_text(module, encoding="utf-8")
            config_path.write_text(config, encoding="utf-8")

            # Read before running. A draft rejected here costs a second instead of the minutes
            # the mutation gate takes to reach the same conclusion, and the round it saves is a
            # round spent on a better draft.
            if complaints := preflight(module, config, module_path.name, vocab):
                result = {}
            else:
                result = score(policy, module_path, event_schema=event_schema, mutants=mutants)
                complaints = assess(result, config)

            draft = Draft(number=n, module=module, config=config, accepted=not complaints,
                          complaints=complaints, holds=result.get("holds"),
                          caught=result.get("caught"), output=result.get("output", ""))
            run.drafts.append(draft)
            if on_draft:
                on_draft(draft)

            if draft.accepted:
                run.accepted = draft
                return run

            feedback = draft.feedback()
    finally:
        # Put back whatever was there if nothing was accepted. A rejected draft must not replace a
        # property somebody wrote by hand, and leaving the last failed attempt on disk is exactly
        # how that would happen.
        if run.accepted is None:
            for path, before in ((module_path, existing[0]), (config_path, existing[1])):
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(before, encoding="utf-8")

    return run


def manual() -> str:
    """The article the MCP server serves to any agent asking how to write one of these.

    Handed to the drafter directly rather than left to be fetched: the loop is not conversational,
    so there is no turn in which to go and look it up. It carries the two things a drafter gets
    wrong on its own -- that a temporal claim needs a hand-built session, and that `time` is in
    seconds.
    """
    return (REPO / "src" / "Anchor.MCPServer" / "knowledge"
            / "writing-a-property-module.md").read_text(encoding="utf-8")


def draft_prompt(vocab: dict, intent: str, feedback: str = "") -> str:
    """What to ask for one draft. Shared with agent.pipeline, which runs the drafter as a node."""
    # THE MODULE NAME, said plainly and first. TLA+ requires the module name to match its file
    # name, this loop chooses the file name, and the skeleton in the vocabulary carries a
    # DIFFERENT name derived from the policy -- so a draft that copies the skeleton's header is
    # written to a file it does not match and fails to parse, with an error that mentions neither.
    required = vocab.get("requiredModuleName", "Intent")
    prompt = (f"The module MUST be named exactly `{required}`, so its first line is:\n"
              f"    ---------------------------- MODULE {required} "
              f"----------------------------\n"
              f"Do not copy the module name from the skeleton below; it is a different name.\n\n"
              f"How to write one:\n\n{manual()}\n\n"
              f"---\n\nThe vocabulary for THIS policy:\n\n"
              f"```json\n{json.dumps(vocab, indent=2)[:8000]}\n```\n\n"
              f"The intention to state formally:\n\n{intent}")
    if feedback:
        prompt += f"\n\nYour previous attempt was rejected:\n{feedback}\n\nTry again."
    return prompt


def retry_prompt(feedback: str) -> str:
    """What to ask for round 2 and after, when the drafter still has round 1 in its context.

    THE MANUAL IS 15 KB AND THE VOCABULARY IS ANOTHER 8, and `draft_prompt` sends both. A Strands
    `Agent` keeps its conversation, and the drafting loop reuses ONE agent across rounds -- so a
    second round built from `draft_prompt` sends the whole first exchange AND a fresh copy of the
    manual, the vocabulary and the intent on top of it.

    Measured on a live run, twice, and the arithmetic is exact: round 1 was 6,399 in / 6,580 out,
    and round 2's input was 19,501 = 12,979 + 6,522. That 6,522 is `draft_prompt` again, charged a
    second time for text the model is already looking at.

    So later rounds send the feedback and nothing else. The model keeps everything it needs --
    including its own previous module, which is what "return the whole module again" refers to and
    the reason the history is worth keeping at all.
    """
    return (f"Your previous attempt was rejected:\n\n{feedback}\n\n"
            f"Return the two files again, between the same ===MODULE=== and ===CONFIG=== markers, "
            f"with the same module name. Everything you were told before still applies.")


def parse_draft(text: str) -> tuple[str, str]:
    """The two files out of one reply. A missing marker is a failed draft, not a crash."""
    module, _, config = text.partition("===CONFIG===")
    module = module.partition("===MODULE===")[2] or module

    # Fences survive instructions not to use them, and stripping one here beats one more line of
    # prompt nobody can enforce.
    def unfence(s: str) -> str:
        s = s.strip()
        if s.startswith("```"):
            lines = s.splitlines()
            s = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return s.strip() + "\n"

    return unfence(module), unfence(config) if config.strip() else ""


DRAFTER_PROMPT = (
        "You write TLA+ property modules that state what a Dogwood authorization policy is "
        "SUPPOSED to mean, so that a model checker can test the policy against the claim.\n\n"
        "You are given the module's VOCABULARY as JSON -- the actions, event kinds, input and "
        "output fields with their value domains, and the constructors. Name only what is there; "
        "anything else will not compile.\n\n"
        # NOT JSON. TLA+ is backslash-heavy -- `\\*`, `\\/`, `\\in` -- and every one of those is an
        # invalid JSON escape, so a model embedding a module in a JSON string produces something
        # that will not parse however careful it is being. Delimiters have no escaping rules.
        "Return the two files separated by these exact markers and nothing else:\n\n"
        "===MODULE===\n"
        "<the complete .tla file text>\n"
        "===CONFIG===\n"
        "<the complete .cfg file text, naming every invariant with INVARIANT lines>\n\n"
        "The module must be named as instructed, EXTEND PolicyUnderTest, and state the claim as "
        "one or more named invariants. State the claim about concrete actions and values the "
        "policy actually names: a claim that ranges over nothing passes without checking "
        "anything, which is worse than failing.\n\n"
        # THE RULES, short and first-class. Each was a recorded way a draft failed, and each also sits
        # somewhere in the 23 KB manual -- where it competed with everything else and was missed. The
        # ones a check can see are ALSO checked (preflight, the decision probe, mutation scoring);
        # a rule here shapes what is tried, a check decides what is kept.
        "RULES. Each one is a way an earlier draft failed.\n\n"
        "1. Decide from the REQUIREMENT which sessions must be ALLOWED and which DENIED before you "
        "evaluate anything. Never write a claim because `evaluate` showed the policy does it: that "
        "restates the policy, and passes whatever the policy says.\n"
        "2. Include at least one claim that ONE specific, fully compliant session -- every "
        "prerequisite present -- is ALLOWED. If every claim says 'must refuse', no mutation that "
        "removes a permission can break your module. Keep it to that session: 'X requires Y' "
        "means 'without Y, refused', never 'with Y, always allowed'.\n"
        "3. Put every prerequisite event the policy needs into the session before the decision, "
        "or the policy refuses everything and your claims test nothing.\n"
        "4. Put each value where the policy reads it: a field listed in the vocabulary's "
        "inputFields goes in an event's input record (Ev's third argument), one in outputFields "
        "in its output record (the fourth).\n"
        "5. VARIABLES hold plain values; tag them only inside event records. Compare a tagged "
        "value with = and #, but order the number inside: x.v <= 22, never x <= Num(22).\n"
        "6. Times are in SECONDS.\n\n"
        # CHECK YOUR OWN WORK. Without this the tools are present and unused: a model asked for two
        # files returns two files. The instruction is specific about WHEN, because a check run
        # after the answer has been given is a check nobody acts on.
        "YOU HAVE TOOLS, AND YOU ARE EXPECTED TO USE THEM BEFORE YOU ANSWER.\n\n"
        "  check_module(module, config)      does it compile, and does it evaluate\n"
        "  what_it_forbids(module, config)   what each claim forbids, and over how many states\n"
        "  evaluate(expr, module, config)    the value of one expression, to settle a question\n\n"
        "Call `check_module` on every draft and fix what it reports, then call it again. Only "
        "return the two files once it reports no problem -- or, if you cannot get there, return "
        "your best attempt anyway rather than nothing.\n\n"
        "`check_module` will sometimes say the property does NOT hold on the policy. That is an "
        "acceptable answer and often the right one: a property that fails has already shown it can "
        "tell one policy from another. NEVER weaken a claim to make it hold.")


def model_author(model=None):
    """A drafter backed by a language model. The only part that costs money."""
    from strands import Agent

    from agent.policy_agent import build_model

    agent = Agent(model=model or build_model(), callback_handler=None,
                  system_prompt=DRAFTER_PROMPT)

    def propose(vocab: dict, intent: str, feedback: str) -> tuple[str, str]:
        # A reply missing the markers is a failed draft, not a crash: the loop says so and asks
        # again, which is what it is for. The empty config is what `assess` will complain about.
        return parse_draft(str(agent(draft_prompt(vocab, intent, feedback))).strip())

    return propose


def show(draft: Draft) -> None:
    status = "ACCEPTED" if draft.accepted else "rejected"
    caught = "" if draft.caught is None else f", caught {draft.caught} mutant(s)"
    holds = {True: "holds", False: "does not hold", None: "no verdict"}[draft.holds]
    print(f"\n--- draft {draft.number}: {status} ({holds}{caught}) " + "-" * 28, file=sys.stderr)
    for c in draft.complaints:
        print(f"  {c}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policy", type=Path, help="the .dw policy the claim is about")
    ap.add_argument("--intent", type=str, default=None,
                    help="what the policy is supposed to mean, in words. MUST come from outside "
                         "the policy -- a requirement, a comment, what somebody asked for")
    ap.add_argument("--intent-file", type=Path, default=None, help="the same, from a file")
    ap.add_argument("--name", type=str, default="Intent",
                    help="the module name, and so the file name (default: Intent)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where to write the module (default: beside the policy)")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--mutants", type=int, default=8,
                    help="how many broken versions of the policy to test the draft against")
    ap.add_argument("--event-schema", type=Path, default=None)
    args = ap.parse_args()

    intent = args.intent or (args.intent_file.read_text(encoding="utf-8")
                             if args.intent_file else None)
    if not intent:
        print("--intent or --intent-file is required: a property module states an INTENTION, and "
              "one derived from the policy itself would only restate it.", file=sys.stderr)
        return 2

    print(f"drafting {args.name}.tla for {args.policy.name}\n"
          f"up to {args.rounds} round(s); each one makes live model calls\n", file=sys.stderr)

    run = author(args.policy, intent, model_author(), rounds=args.rounds,
                 event_schema=args.event_schema, mutants=args.mutants,
                 out_dir=args.out_dir, module_name=args.name, on_draft=show)

    if run.accepted is None:
        print(f"\nNO USABLE DRAFT after {len(run.drafts)} round(s). Nothing was written.",
              file=sys.stderr)
        return 1

    out = (args.out_dir or args.policy.parent) / f"{args.name}.tla"
    print(f"\nwrote {out} and its .cfg", file=sys.stderr)

    # THE CHECKPOINT. "Read it before trusting a finding that rests on it" is advice nobody acts
    # on when acting on it means reading TLA+ somebody else wrote. This is the same instruction
    # with the reading already done: what each claim forbids, and which of the states it ranges
    # over its condition even applies to.
    from checker.explain import Module, explain, render     # noqa: PLC0415

    print("\n" + render(explain(Module(run.accepted.module, run.accepted.config, out.name))),
          file=sys.stderr)

    print("\nTHIS IS A DRAFT. It is a formal statement of your prose, written by a model, and\n"
          "whether it captures what you meant is the one question no tool here answers -- the\n"
          "`forbids` lines above are that question, asked in a form you can answer.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
