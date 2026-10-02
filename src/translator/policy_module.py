"""Policy text to `PolicyUnderTest.tla` -- the module every check extends.

A policy is checked by generating this and then extending it. `Vacuity.tla` extends it to ask the
three questions that need no knowledge of intent; a property module someone writes themselves
extends it to ask whether the policy means what they said it means. Same seam, both times:

    policy.dw ──> PolicyUnderTest.tla ──┬──> Vacuity.tla     is any rule inert?
                                        └──> Yours.tla       does it mean what I said?

THE REQUEST SPACE IS DERIVED FROM THE POLICY'S OWN LITERALS, and that is worth knowing before
relying on it. Each field's domain is every value the policy compares it against, plus one it does
not, so that both matching and not-matching stay reachable. It is small on purpose -- the state
space is the product of the domains.

The consequence bites anything that asks a question the policy does not already talk about. A
property about `origin = "external"` against a policy that never writes "external" is evaluated
over a request space containing no such request: it holds VACUOUSLY, and reports success having
looked at nothing. `--against` guards this by spanning both files; a property module should state
its own request space rather than borrow this one.
"""

from __future__ import annotations

from pathlib import Path

from .emit import policy_seq
from .parse import DAY_MS, SYSTEM_NOW, TLC_MAX_INT, Unsupported, like_matches, pattern_witnesses

KINDS = ["request", "response", "error"]
DECISION_KIND = "request"


# ---------------------------------------------------------------------------- vocabulary
def walk(node, seen: dict) -> None:
    """Collect the vocabulary a policy actually reads, so nothing unused is modelled.

    Field LITERALS are collected too. A field's domain is the values the policy compares it
    against plus one it does not, so both matching and not-matching stay reachable -- which is
    what lets fields move independently instead of sharing one domain.
    """
    if not isinstance(node, dict):
        return

    if pred := node.get("pred"):
        if pred.get("action"):
            seen["actions"].add(pred["action"])
        if pred.get("kind"):
            seen["kinds"].add(pred["kind"])
        for b in pred.get("binds", []):
            side = "input" if b["side"] == "input" else "output"
            if b["side"] not in ("input", "output"):
                continue
            seen[side].add(b["field"])
            if b["kind"] == "lit":
                seen["literals"].setdefault((side, b["field"]), set()).add(b["value"])

    if node.get("op") == "cmp":
        seen["input"].add(node["field"])
        seen["literals"].setdefault(("input", node["field"]), set()).add(node["value"])

    if node.get("op") == "inrange":
        # Two addresses, and both are needed: one the CIDR contains, so the guard can be true, and
        # one it does not, so "outside the range" is reachable. A /32 contains exactly one address,
        # which is why the outside witness is derived by flipping an octet rather than by adding.
        seen["input"].add(node["field"])
        net, prefix = node["net"], node["prefix"]
        inside = tuple(net)
        outside = tuple(net[:3] + [(net[3] + 1) % 256]) if prefix == 32 else \
            tuple([(net[0] + 1) % 256] + net[1:]) if prefix >= 8 else \
            tuple([(net[0] + 128) % 256] + net[1:])
        lits = seen["literals"].setdefault(("input", node["field"]), set())
        lits.add(inside)
        lits.add(outside)

    if node.get("op") == "like":
        # A pattern names no literal, so it must contribute the values that make it decidable:
        # one the pattern matches, and one it does not. See this module's `like` note.
        seen["input"].add(node["field"])
        hit, miss = pattern_witnesses(node["pattern"])
        lits = seen["literals"].setdefault(("input", node["field"]), set())
        lits.add(hit)
        if miss is not None:
            lits.add(miss)
        # Recorded so `vocabulary` can refuse a field carrying two of them; see the note there.
        seen["patterns"].setdefault(("input", node["field"]), set()).add(
            tuple(node["pattern"]))

    if node.get("op") == "cmp2":
        # Both sides are request fields. Neither names a literal, so both take the default
        # numeric range -- which needs at least two values for the comparison to go either way.
        seen["input"].add(node["field"])
        seen["input"].add(node["other"])

    for key in ("term", "atom", "left", "cond", "agg"):
        walk(node.get(key), seen)
    for child in node.get("args", []) or []:
        walk(child, seen)


def vocabulary(policies: list[dict], amounts: int = 2, max_fields: int = 4) -> dict:
    seen = {"actions": set(), "kinds": set(), "input": set(), "output": set(),
            "literals": {}, "patterns": {}}
    for p in policies:
        seen["actions"].update(p["actions"])
        walk(p["cond"], seen)

    # Two `like` patterns on ONE field need a value satisfying BOTH, or the conjunction looks
    # unsatisfiable and the permit is reported VACUOUS though it is live -- `stock like "A*" &&
    # stock like "*L"` is satisfied by "AAPL", while the per-pattern witnesses "A" and "L"
    # satisfy one pattern each. A false VACUOUS tells someone to delete a working rule.
    #
    # Since TLC evaluates the real pattern, adding a candidate can never make something falsely
    # live; it can only fail to be found. So look for one, and refuse only if the search fails,
    # where "no such string exists" and "we did not look hard enough" are indistinguishable.
    for (side, field), pats in seen["patterns"].items():
        if len(pats) < 2:
            continue
        joint = joint_witness(pats)
        if joint is None:
            raise Unsupported(
                f"{side}.{field} is constrained by {len(pats)} `like` patterns at once and no "
                f"value satisfying all of them could be constructed; deciding that needs glob "
                f"intersection, which is not modelled")
        seen["literals"].setdefault((side, field), set()).add(joint)

    # Each field gets its own domain, so fields move independently. The bound is on state space,
    # not on soundness: the request space is the product of the domains, so it grows as
    # values^fields. Refused above the bound rather than run until it is hopeless.
    fields = len(seen["input"]) + len(seen["output"])
    if fields > max_fields:
        raise Unsupported(
            f"policy reads {fields} input/output fields; the request space is the product of "
            f"their domains, so this would explode (limit {max_fields}, raise with --max-fields)")

    unknown = seen["kinds"] - set(KINDS)
    if unknown:
        raise Unsupported(f"event kinds outside AgentCore's convention: {', '.join(sorted(unknown))}")

    # The wall clock is a time of day, so it never leaves [0h, 24h). Unbounded, a policy demanding
    # `toTime() >= duration("25h")` would find a witness at 25h and be reported live when nothing
    # can ever satisfy it.
    seen["domains"] = {key: field_domain(lits, amounts,
                                         (0, DAY_MS - 1) if key[1] == SYSTEM_NOW else None)
                       for key, lits in _all_fields(seen)}
    return seen


def _all_fields(seen: dict):
    for side in ("input", "output"):
        for field in sorted(seen[side]):
            yield (side, field), seen["literals"].get((side, field), set())


def joint_witness(patterns) -> str | None:
    """A string every one of `patterns` matches, or None if none was constructed.

    The candidates are what each pattern literally requires -- its non-wildcard characters, in
    order -- tried alone and concatenated in both orders. That is enough for the shapes a prefix
    or suffix test produces (`A*` with `*L` gives "AL"), and deliberately not a decision
    procedure: the caller treats None as "refuse", never as "unsatisfiable".
    """
    pats = sorted(patterns, key=len)
    parts = ["".join(e for e in pat if e is not None) for pat in pats]

    candidates = list(parts)
    for i, a in enumerate(parts):
        for j, b in enumerate(parts):
            if i != j:
                candidates.append(a + b)
    candidates.append("".join(parts))

    for cand in candidates:
        if all(like_matches(list(pat), cand) for pat in pats):
            return cand
    return None


def field_domain(literals: set, amounts: int, bounds: tuple[int, int] | None = None) -> list:
    """The values one field may take: every literal the policy names, plus ones it does not.

    The extra values are what make "this field does not match" reachable. Without them a field
    compared only against `true` would always be true, and a policy that depends on it being
    false would be reported vacuous when it is not.

    A NUMERIC FIELD NEEDS ONE ON EACH SIDE, and for a long time it only got one above. A domain of
    `{3, 4}` for a field the policy compares with `< 3` contains nothing that satisfies it, so an
    ordinary `context.input.cost < 25000` came back **VACUOUS** -- a working permit reported as
    dead, which is the one wrong answer this checker must not give, and the advice that follows it
    is to delete the rule. `==` and `>` were satisfiable and `<` and `<=` were not, which is why
    it survived: every fixture that would have caught it compared for equality.

    A field with no literals -- bound only by `_` or by a join with the request's own context --
    gets a small numeric range, which needs at least two values for a join to mean anything.

    `bounds` is the range a numeric field can actually take. Every value is clamped into it, so a
    literal outside it contributes the nearest value that exists rather than one that does not.
    """
    if not literals:
        return [("n", x) for x in range(1, max(2, amounts) + 1)]

    def kind_of(v):
        if type(v) is bool:
            return "b"
        if type(v) is tuple:      # four octets -- an address, not a string of one
            return "a"
        return "n" if type(v) is int else "s"

    kinds = {kind_of(v) for v in literals}
    if len(kinds) > 1:
        raise Unsupported(f"field compared against mixed value kinds: {sorted(kinds)}")
    kind = kinds.pop()

    values = [(kind, v) for v in sorted(literals, key=str)]
    if kind == "b":
        # A boolean has only the two, and both are already reachable.
        return [("b", False), ("b", True)]
    if kind == "a":
        # Both witnesses are already here, and inventing a third address would say nothing the
        # two do not.
        return values
    if kind != "n":
        values.append(("s", "\u0000none"))
        return values

    # ONE ON EACH SIDE. Every comparison operator then has both a witness and a counter-witness in
    # the domain; with only the value above, `<` and `<=` had neither. Clamped to what TLC can
    # hold, because a literal may sit at the very edge of the range and stepping off it would
    # generate a model that does not run.
    values.append(("n", min(max(literals) + 1, TLC_MAX_INT)))
    values.append(("n", max(min(literals) - 1, -TLC_MAX_INT)))
    if bounds:
        lo, hi = bounds
        values = [("n", min(max(v, lo), hi)) for _, v in values]
    return sorted(set(values), key=lambda kv: kv[1])


def tla_set(names) -> str:
    return "{" + ", ".join(f'"{n}"' for n in sorted(names)) + "}"


def tla_val(kind: str, value) -> str:
    """One tagged scalar. Kind travels with the value so TLC never compares across kinds."""
    if kind == "b":
        return f'[k |-> "b", v |-> {"TRUE" if value else "FALSE"}]'
    if kind == "n":
        return f'[k |-> "n", v |-> {value}]'
    if kind == "a":
        return f'[k |-> "a", v |-> <<{", ".join(str(o) for o in value)}>>]'
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'[k |-> "s", v |-> "{escaped}"]'


def tla_domains(vocab: dict, side: str) -> str:
    """`[field |-> {values}, ...]` -- what each field of one side may take."""
    fields = sorted(vocab[side])
    if not fields:
        # An empty record. `[f \in {} |-> ...]` is the only way to write one in TLA+.
        return '[f \\in {} |-> {}]'
    entries = ", ".join(
        f"{f} |-> {{" + ", ".join(tla_val(k, v) for k, v in vocab["domains"][(side, f)]) + "}"
        for f in fields)
    return f"[{entries}]"


def tla_all_values(vocab: dict) -> str:
    seen, out = set(), []
    for key in sorted(vocab["domains"]):
        for k, v in vocab["domains"][key]:
            if (k, v) not in seen:
                seen.add((k, v))
                out.append(tla_val(k, v))
    return "{" + ", ".join(out) + "}" if out else "{}"


def generate_policy_module(source: Path, policies: list[dict], vocab: dict,
             other: list[dict] | None = None, other_name: str = "",
             keys: list[str] | None = None) -> str:
    body = policy_seq(policies)
    # `Other` is the set compared against when Target = 0. With no second file it is `Policies`,
    # which the spec never reads in that case -- Target is then a rule index.
    other_body = policy_seq(other) if other is not None else None

    other_decl = (f"\\* The second set, from {other_name}. Compared against Policies at every\n"
                  f"\\* decision, so a divergence is a session where the edit changed behaviour.\n"
                  f"Other ==\n  <<\n{other_body}\n  >>\n"
                  if other_body is not None else "Other == Policies\n")

    return f"""\\* GENERATED by src/translator/policy_module.py from {source.name} -- do not edit.
\\*
\\* Translated by the parser that agrees with the Dogwood reference implementation on 919 recorded
\\* corpus pairs. Vacuity.tla checks THESE records, so what is model-checked is the policy as
\\* written rather than as paraphrased.
---------------------------- MODULE PolicyUnderTest ----------------------------
EXTENDS Integers, Sequences

Source == "{source.name}"

\\* The vocabulary is lifted from the policy text: only actions, event kinds and input/output
\\* fields some condition actually reads are modelled. A policy that joins on nothing costs nothing.
Actions      == {tla_set(vocab["actions"])}
Kinds        == {tla_set(vocab["kinds"] | {DECISION_KIND})}
InputFields  == {tla_set(vocab["input"])}
OutputFields == {tla_set(vocab["output"])}
DecisionKind == "{DECISION_KIND}"

\\* Each field's own domain: every literal the policy compares it against, plus one it does not,
\\* so that both matching and not-matching are reachable. Fields move independently, which is
\\* what lets a policy reading several of them be explored at all.
InputDomain  == {tla_domains(vocab, "input")}
OutputDomain == {tla_domains(vocab, "output")}
AllValues    == {tla_all_values(vocab)}

\\* The fields a universal pin partitions on. Empty means global-trace semantics -- which is the
\\* `unpinned` preset, NOT the shipped default. Vacuity.tla gives a session two callers when this
\\* is non-empty, so a partition has something to exclude.
PinKeys == {tla_set(keys or [])}

\\* ---- for a property module extending this one --------------------------------------------
\\* Scalars are TAGGED with their kind so TLC refuses a cross-kind comparison rather than quietly
\\* answering one. Write `Num(22)`, never `22`.
\\* An address is FOUR OCTETS, never a 32-bit number: TLC works in Java ints and stops at
\\* 2147483647, so 208.4.4.0 -- 3489924096 -- is not a value it can hold.
Addr(a, b, c, d) == [k |-> "a", v |-> <<a, b, c, d>>]
Str(x)  == [k |-> "s", v |-> x]
Num(x)  == [k |-> "n", v |-> x]
Bool(x) == [k |-> "b", v |-> x]
Anon    == Str("caller")

NoFields == [f \\in {{}} |-> Str("")]

\\* ONE EVENT AT A CHOSEN TIME AND KIND, which is what a claim about a SESSION is built from.
\\*
\\* `time` IS IN SECONDS. The evaluator compares it against a window width directly --
\\* `t - trace[i].time <= window` -- so a claim about a 15-minute window needs events 900 apart,
\\* not two. This is the one thing that catches people out, because the built-in questions
\\* explore sessions whose events are one second apart: a long window can never age out there,
\\* and only a hand-built trace can put a decision on the far side of one.
Ev(action, kind, input, output, time) ==
    [time      |-> time,
     action    |-> action,
     kind      |-> kind,
     input     |-> input,
     output    |-> output,
     principal |-> Anon,
     resource  |-> Anon,
     session   |-> Anon,
     pins      |-> [k \\in PinKeys |-> Anon]]

\\* One request, at time 1, with no outputs -- the shorthand for a per-request claim, where
\\* "what does this policy decide for this request" needs no session at all.
Request(action, input) == Ev(action, DecisionKind, input, NoFields, 1)

\\* NOTE WHAT IS ABSENT: there is no `Inputs`. The request space derivable here comes from the
\\* literals THIS POLICY names, so a claim about a value it never mentions would range over no
\\* such request and hold vacuously. State the requests your claim is about.

Policies ==
  <<
{body}
  >>

{other_decl}
=============================================================================
"""
