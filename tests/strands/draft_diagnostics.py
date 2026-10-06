"""The mistakes recorded drafts made are named precisely, and the drafter is told the rules.

    python tests/strands/draft_diagnostics.py

Drawn from about 45 recorded drafting attempts. Three checks and one set of rules:

    author.tagged_orderings   STATIC, in preflight: an ordering operator beside a tag constructor
                              (`x <= Num(22)`). `Num(22)` is a record, so it fails at run time, and an
                              earlier article taught it as the right form. Seven drafts died this way
    author.misplaced_fields   STATIC, in preflight: a value put in the half of an event the policy
                              never reads it from. One recorded draft did this and passed every gate
                              while testing nothing
    author.diagnose           AFTER TLC: which tagging mistake its error message points to. Run
                              against TLC's real output for each mistake, not against typed strings
    the RULES                 in the drafter's system prompt and the vocabulary's rules

Both static checks REJECT, so a false positive would throw away a good draft. Every real property
module in the repo is put to them, and none may be flagged.

THIS FILE IS PLAIN ASCII, and so is everything it prints.
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "src", REPO / "src" / "agent"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from agent import author  # noqa: E402
from translator.tlc import run_eval  # noqa: E402

failures = 0


def check(what: str, ok: bool, detail: str = "") -> None:
    global failures
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures += 1
        if detail:
            print("      " + detail[:300])


def flagged(text: str) -> int:
    return len(author.tagged_orderings(text))


# --- the static check: what it must catch --------------------------------------------------------
for text in ("Ok == x <= Num(2500)", "Ok == Num(1) > 0", "Ok == x \\leq Num(3)",
             "Ok == Num(1) >= y", "Ok == x < Str(\"a\")"):
    check(f"flags `{text[6:]}`", flagged(text) == 1, str(author.tagged_orderings(text)))
complaint = author.tagged_orderings("A == 1\nOk == x <= Num(2500)")[0]
check("and names the line, the expression and the fix",
      complaint.startswith("line 2:") and "x.v <= 2500" in complaint, complaint)

# --- what it must NOT flag ------------------------------------------------------------------------
for text in ("Ok == [a |-> Num(1)]", "Ok == <<Num(1), Num(2)>>", "Ok == x \\in {Num(1)}",
             "Ok == s = Str(\"a\")", "Ok == x.v <= 2500", "Ok == x = Num(1) => y",
             "Ok == y # Num(1)", "M == INSTANCE N WITH c <- Num(1)", "F == [x \\in S |-> Num(1)]",
             "Ok == TRUE \\* x <= Num(1), in a comment", "Ok == \"x <= Num(1)\" = \"s\"",
             "(* x <= Num(1)\n   across lines *)\nOk == TRUE"):
    check(f"leaves `{text[:40]}` alone", flagged(text) == 0, str(author.tagged_orderings(text)))

# Every real property module, all of them correct. A rejection that fired on any of them would throw
# away a good draft, so this is the check that matters most.
modules = sorted(p for d in ("examples", "tests/policies")
                 for p in (REPO / d).rglob("*.tla")
                 if "traces" not in p.parts and "testprop" not in p.parts
                 and "testoutput" not in p.parts and p.name not in ("PolicyUnderTest.tla",))
hits = {str(p.relative_to(REPO)): author.tagged_orderings(p.read_text(encoding="utf-8"))
        for p in modules}
hits = {k: v for k, v in hits.items() if v}
check(f"no false alarm on any of the {len(modules)} real property modules in the repo",
      not hits and len(modules) > 10, str(hits))

# --- diagnose, on TLC's real output ---------------------------------------------------------------
TAGS = ("---- MODULE Tags ----\nEXTENDS Integers\n"
        "Num(x) == [k |-> \"n\", v |-> x]\nStr(x) == [k |-> \"s\", v |-> x]\n"
        "VARIABLE z\nInit == z = 0\nNext == UNCHANGED z\nSpec == Init /\\ [][Next]_z\n====\n")
expected = {
    "Num(1) <= Num(2)": "ordering operator",
    "2 <= Num(1)": "ordering operator",
    "Str(\"a\") = \"a\"": "compared a TAGGED value with a plain one",
    "\"a\" = Str(\"a\")": "compared a TAGGED value with a plain one",
    "1 = Num(1)": "compared a TAGGED value with a plain one",
    "1 = FALSE": "Init`-domain pattern",
}
with tempfile.TemporaryDirectory(prefix="anchor-tagging-") as scratch:
    work = Path(scratch)
    (work / "Tags.tla").write_text(TAGS, encoding="utf-8")
    for expr, says in expected.items():
        ok, out = run_eval(expr, "Tags", work)
        said = author.diagnose(out) or ""
        check(f"TLC's error for `{expr}` is diagnosed as: {says}", not ok and says in said,
              said or out[-300:])
    ok, out = run_eval("CHOOSE x \\in {} : TRUE", "Tags", work)
    check("an unrelated TLC error gets no tagging diagnosis", not ok and author.diagnose(out) is None,
          str(author.diagnose(out)))

# --- placement: a value in the half of an event the policy never reads it from --------------------
# The policy reads `profile_id` from get_client_profile's INPUT, and reads no output field at all.
vocab = author.describe(REPO / "examples" / "aws1" / "02-output-to-input.dw")
check("the vocabulary reads profile_id from inputs only",
      [f["name"] for f in vocab["inputFields"]] == ["profile_id"] and vocab["outputFields"] == [],
      str(vocab.get("inputFields")) + str(vocab.get("outputFields")))


def session(lookup_in: str, lookup_out: str, extra: str = "") -> str:
    return (extra +
            "Session(a, b) ==\n"
            f"  << Ev(\"get_client_profile\", \"response\", {lookup_in}, {lookup_out}, 1),\n"
            "     Ev(\"execute_trade\", \"request\", [profile_id |-> Num(b)], NoFields, 2) >>\n")


# THE RECORDED DRAFT's two events, verbatim apart from the variable names.
said = author.misplaced_fields(session("NoFields", "[profile_id |-> Num(a)]"), vocab)
check("the recorded draft is flagged: profile_id in the lookup's OUTPUT", len(said) == 1
      and "`profile_id`" in said[0] and "only from an event's INPUT" in said[0]
      and said[0].startswith("line 2:"), str(said))
check("...and the corrected draft is not",
      author.misplaced_fields(session("[profile_id |-> Num(a)]", "NoFields"), vocab) == [])
check("a value echoed in both halves is left alone",
      author.misplaced_fields(session("[profile_id |-> Num(a)]", "[profile_id |-> Num(a)]"),
                              vocab) == [])
check("a value the policy reads from neither half is left alone",
      author.misplaced_fields(session("[profile_id |-> Num(a)]", "[result |-> Bool(TRUE)]"),
                              vocab) == [])
check("a record built by a helper definition is read through it",
      len(author.misplaced_fields(session("NoFields", "Looked(a)",
                                          "Looked(i) == [profile_id |-> Num(i)]\n"), vocab)) == 1)
check("an argument it cannot read is skipped, not guessed",
      author.misplaced_fields(session("NoFields", "lookup"), vocab) == [])

# Real modules, each against its own policy. Both halves of an event appear in these.
for module, policy, kw in (("tests/policies/firewall.tla", "tests/policies/firewall.dw", {}),
                           ("examples/dogwoodrepo1/SuccessfulRead.tla",
                            "examples/dogwoodrepo1/skill-set.dw", {}),
                           ("examples/aws1/EmptyTrajectory.tla", "examples/aws1/agent-policy.dw", {}),
                           ("examples/aws2/CumulativeCap.tla", "examples/aws2/agent-policy.dw",
                            {"max_fields": 8})):
    v = author.describe(REPO / policy, **kw)
    said = author.misplaced_fields((REPO / module).read_text(encoding="utf-8"), v)
    check(f"no false alarm on {module}", not v.get("_failed") and said == [],
          str(said) or str(v.get("_why")))

# --- the rules: in the drafter's system prompt, and in the vocabulary every agent is given --------
check("the drafter's system prompt states the rules",
      "RULES." in author.DRAFTER_PROMPT and "fully compliant session" in author.DRAFTER_PROMPT
      and "inputFields" in author.DRAFTER_PROMPT and "x.v <= 22" in author.DRAFTER_PROMPT)
rules = " ".join(vocab.get("rules_for_writing_one", []))
check("the vocabulary's rules carry them to MCP agents too",
      "fully compliant session" in rules and "outputFields" in rules and "x.v <= 22" in rules, rules)
# THE EDGE OF EACH THRESHOLD, from the requirement. aws2's supervisor-approval module used the
# policy's own literals, so a $1000 threshold passed -- and the reviewer, shown those values, agreed.
check("the drafter is told to range over the value just past each threshold",
      "JUST PAST" in author.DRAFTER_PROMPT and "500 and 501" in author.DRAFTER_PROMPT)
check("...and so are MCP agents", "just past" in rules and "500 and 501" in rules, rules)

print()
print("all passed" if not failures else f"{failures} FAILED")
sys.exit(1 if failures else 0)
