"""What a property module FORBIDS, in English, before anything is checked.

    python src/checker/explain.py examples/aws1/TrustDecay10.tla

THE ONE PLACE THE LITERATURE AGREES AUTONOMY FAILS is the formulation of the property itself.
Everything downstream of a property is mechanical and checkable -- TLC either finds a counterexample
or does not -- and everything upstream is a person saying what they meant. The step between is the
one nothing verifies: a property that says something *other* than what its author meant is checked
just as rigorously as one that says what they meant, and passes just as convincingly.

So this prints, per claim, the sentence a reviewer actually has to agree with:

    forbids:  gap is greater than 600,
              and yet the policy GRANTS it

If that sentence is not something you would object to seeing happen, the check is going to pass and
tell you nothing -- and it will do it in the same green letters as a check that tested your
intention. Approving the `forbids` line before the run is the whole point.

WHY THIS READS THE MODULE RATHER THAN ASKING A MODEL TO SUMMARISE IT. An English gloss written by a
model, of a property written by a model, is two drafts of one misunderstanding: whatever the first
got wrong about your intent, the second restates faithfully. So the English here is generated from
the parsed expression -- structure in words, terms quoted as written -- and every part that cannot
be read is reported as unread rather than guessed at.

AND IT COUNTS. A claim shaped `A => B` tests nothing at all in any state where `A` is false, so the
states where `A` HOLDS are the entire experiment. Those are countable here, before TLC runs, because
the domain is enumerable and `A` is usually arithmetic:

    applies:  to 2 of the 6 states:
                gap = 960
                gap = 1800

Zero of them is the failure this module exists to catch -- a claim that will pass having examined
nothing, which is the same defect as a vacuous policy and just as invisible in a green run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Exit codes, matching the checker's: 0 answered, 2 could not read the module, and this fourth one
# for a claim that will pass having tested nothing. Same number as `properties.py`'s WeakProperty
# because it is the same finding arrived at more cheaply -- there, by breaking the policy and
# noticing the property did not care; here, by counting the states the claim even applies to.
VACUOUS_CLAIM = 4


# ---------------------------------------------------------------------------- values
class Unknown:
    """A value this reader could not compute. Propagates, and is never mistaken for a result.

    The distinction it keeps is the one that matters: "the condition is false here" and "I could
    not tell whether the condition holds here" look identical in a count and mean opposite things.
    """

    def __repr__(self) -> str:
        return "?"

    def __bool__(self) -> bool:                      # never truthy by accident
        raise TypeError("the truth of an unknown value is not a bool")


UNKNOWN = Unknown()

# "this is not one of mine", which UNKNOWN cannot say: UNKNOWN is a legitimate RESULT, so a lookup
# returning it would be indistinguishable from an operator that exists and could not be computed.
NOTHING = object()


@dataclass(frozen=True)
class Tag:
    """A tagged scalar -- `Num(22)`, `Str("local")`, `Bool(TRUE)`, `Addr(10,0,0,1)`."""

    kind: str
    value: Any


@dataclass(frozen=True)
class Rec:
    """A record, as `[port |-> Num(22), origin |-> Str("local")]`."""

    fields: tuple[tuple[str, Any], ...]

    def get(self, name: str) -> Any:
        return next((v for k, v in self.fields if k == name), UNKNOWN)


@dataclass(frozen=True)
class Seq:
    items: tuple[Any, ...]


def sort_key(v: Any) -> tuple:
    """A stable, HUMAN order for a set of values. Integers numerically, everything else by its
    rendering -- `repr` order would print a domain of seconds as 1, 1800, 300, which reads as a
    mistake in the module rather than in the listing."""
    if isinstance(v, bool):
        return (1, str(v))
    if isinstance(v, int):
        return (0, v)
    if isinstance(v, Tag):
        return sort_key(v.value)
    return (2, show_value(v))


def show_value(v: Any) -> str:
    if isinstance(v, Unknown):
        return "?"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, Tag):
        return show_value(v.value)                   # the tag is machinery, not content
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, Rec):
        return "[" + ", ".join(f"{k} |-> {show_value(x)}" for k, x in v.fields) + "]"
    if isinstance(v, Seq):
        return "<<" + ", ".join(show_value(x) for x in v.items) + ">>"
    if isinstance(v, frozenset):
        return "{" + ", ".join(show_value(x) for x in sorted(v, key=sort_key)) + "}"
    return str(v)


# ---------------------------------------------------------------------------- reading TLA+
class ParseError(Exception):
    """This reader could not read that. Always caught: an unreadable definition is reported as
    unread, never as a claim about the policy."""


def strip_block_comments(text: str) -> str:
    """Remove `(* ... *)`, which nest, leaving newlines so line numbers survive."""
    out, depth, i = [], 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "(*":
            depth += 1
            i += 2
        elif two == "*)" and depth:
            depth -= 1
            i += 2
        else:
            out.append(text[i] if (depth == 0 or text[i] == "\n") else " ")
            i += 1
    return "".join(out)


TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<comment>\\\*[^\n]*)
    | (?P<sep>-{4,}|={4,})
    | (?P<str>"(?:[^"\\]|\\.)*")
    | (?P<num>\d+)
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<bsop>\\/|\\[A-Za-z]+)
    | (?P<op><=>|=>|/\\|\|->|<<|>>|->|\.\.|<=|>=|/=|[-+*/%=#<>~(){}\[\],.:!])
""", re.VERBOSE)


def lex(src: str) -> list[tuple[str, str]]:
    tokens, i = [], 0
    src = strip_block_comments(src)
    while i < len(src):
        m = TOKEN.match(src, i)
        if m is None:
            raise ParseError(f"cannot read {src[i:i + 20]!r}")
        i = m.end()
        kind = m.lastgroup or ""
        if kind in ("ws", "comment", "sep"):
            continue
        tokens.append((kind, m.group()))
    return tokens


# Lowest binding first. `~` sits between the logical connectives and the relations because that is
# where TLA+ puts it: `~x = 1` is `~(x = 1)`, not `(~x) = 1`.
LOGIC = [("<=>",), ("=>",), ("\\/",), ("/\\",)]
RELATIONS = {"=", "#", "/=", "<", ">", "<=", ">=", "\\in", "\\notin", "\\subseteq"}
ADDITIVE = {"+", "-"}
MULTIPLICATIVE = {"*", "\\div", "%"}


class Parser:
    """A recursive-descent reader for the fragment of TLA+ a property module states claims in.

    NOT A TLA+ PARSER, and the difference is deliberate. It reads what the claims in these modules
    are written with -- implication, conjunction, comparison, arithmetic, records, sets, set
    comprehension, quantifiers, `CASE`, `IF` -- and raises on anything else. SANY is the parser
    that decides whether the module is well-formed; this one only has to read it well enough to
    say what it means, and must fail loudly rather than mis-read.
    """

    def __init__(self, tokens: list[tuple[str, str]]):
        self.toks = tokens
        self.i = 0

    # --- plumbing -----------------------------------------------------------------------------
    def peek(self, ahead: int = 0) -> str:
        j = self.i + ahead
        return self.toks[j][1] if j < len(self.toks) else ""

    def kind(self, ahead: int = 0) -> str:
        j = self.i + ahead
        return self.toks[j][0] if j < len(self.toks) else ""

    def take(self, what: str | None = None) -> str:
        if self.i >= len(self.toks):
            raise ParseError(f"ran out of input, expected {what or 'more'}")
        tok = self.toks[self.i][1]
        if what is not None and tok != what:
            raise ParseError(f"expected {what!r}, found {tok!r}")
        self.i += 1
        return tok

    def at(self, *what: str) -> bool:
        return self.peek() in what

    # --- grammar ------------------------------------------------------------------------------
    def expr(self, level: int = 0):
        if level >= len(LOGIC):
            return self.negation()
        ops = LOGIC[level]
        left = self.expr(level + 1)
        while self.at(*ops):
            op = self.take()
            left = ("bin", op, left, self.expr(level + 1))
        return left

    def negation(self):
        if self.at("~"):
            self.take()
            return ("un", "~", self.negation())
        return self.relation()

    def relation(self):
        left = self.additive()
        if self.peek() in RELATIONS:
            op = self.take()
            return ("bin", op, left, self.additive())
        return left

    def additive(self):
        left = self.multiplicative()
        while self.peek() in ADDITIVE:
            op = self.take()
            left = ("bin", op, left, self.multiplicative())
        return left

    def multiplicative(self):
        left = self.postfix()
        while self.peek() in MULTIPLICATIVE:
            op = self.take()
            left = ("bin", op, left, self.postfix())
        return left

    def postfix(self):
        node = self.primary()
        while self.at(".") and self.kind(1) == "name":
            self.take(".")
            node = ("dot", node, self.take())
        return node

    def primary(self):
        kind, tok = self.kind(), self.peek()

        if kind == "num":
            return ("num", int(self.take()))
        if kind == "str":
            return ("str", self.take()[1:-1])
        if tok in ("TRUE", "FALSE"):
            return ("bool", self.take() == "TRUE")
        if tok == "(":
            self.take("(")
            inner = self.expr()
            self.take(")")
            return inner
        if tok == "{":
            return self.set_()
        if tok == "[":
            return self.record()
        if tok == "<<":
            return self.sequence()
        if tok in ("\\A", "\\E"):
            return self.quantifier()
        if tok == "CASE":
            return self.case()
        if tok == "IF":
            return self.if_()
        if kind == "name":
            return self.application()

        raise ParseError(f"cannot read {tok!r}")

    def application(self):
        name = self.take()

        # `D!Decide(...)` -- an operator from an INSTANCE. The instance name carries no meaning
        # here beyond which module it came from, so the two are kept together as one name.
        if self.at("!"):
            self.take("!")
            name = f"{name}!{self.take()}"

        if not self.at("("):
            return ("name", name)

        self.take("(")
        args = []
        if not self.at(")"):
            args.append(self.expr())
            while self.at(","):
                self.take(",")
                args.append(self.expr())
        self.take(")")
        return ("app", name, args)

    def set_(self):
        self.take("{")
        if self.at("}"):
            self.take("}")
            return ("set", [])

        first = self.expr()

        # `{x \in S : P}` -- a filter. Distinguished from a comprehension by where the `\in` is.
        if self.at("\\in") and first[0] == "name":
            self.take("\\in")
            source = self.expr()
            self.take(":")
            pred = self.expr()
            self.take("}")
            return ("filter", first[1], source, pred)

        # `{e : x \in S, y \in T}` -- a comprehension.
        if self.at(":"):
            self.take(":")
            binds = [self.binding()]
            while self.at(","):
                self.take(",")
                binds.append(self.binding())
            self.take("}")
            return ("comp", first, binds)

        items = [first]
        while self.at(","):
            self.take(",")
            items.append(self.expr())
        self.take("}")
        return ("set", items)

    def binding(self) -> tuple[str, Any]:
        name = self.take()
        self.take("\\in")
        return (name, self.expr())

    def record(self):
        self.take("[")
        fields = []
        while not self.at("]"):
            name = self.take()
            self.take("|->")
            fields.append((name, self.expr()))
            if self.at(","):
                self.take(",")
        self.take("]")
        return ("rec", fields)

    def sequence(self):
        self.take("<<")
        items = []
        while not self.at(">>"):
            items.append(self.expr())
            if self.at(","):
                self.take(",")
        self.take(">>")
        return ("seq", items)

    def quantifier(self):
        which = self.take()
        binds = [self.binding()]
        while self.at(","):
            self.take(",")
            binds.append(self.binding())
        self.take(":")
        return ("quant", which, binds, self.expr())

    def case(self):
        self.take("CASE")
        arms, other = [], None
        while True:
            if self.at("OTHER"):
                self.take("OTHER")
                self.take("->")
                other = self.expr()
            else:
                guard = self.expr()
                self.take("->")
                arms.append((guard, self.expr()))
            if not self.at("[]"):
                # `[]` lexes as two tokens, `[` then `]`.
                if self.at("[") and self.peek(1) == "]":
                    self.take("[")
                    self.take("]")
                    continue
                break
        return ("case", arms, other)

    def if_(self):
        self.take("IF")
        cond = self.expr()
        self.take("THEN")
        then = self.expr()
        self.take("ELSE")
        return ("ite", cond, then, self.expr())


BULLET = re.compile(r"^\s*(/\\|\\/)")


def unbullet(src: str) -> str:
    """TLA+'s bulleted conjunction list, as the infix expression it means.

        Init ==                        Init == amount \\in Amounts
            /\\ amount \\in Amounts              /\\ gap \\in Gaps
            /\\ gap \\in Gaps

    THE PARSER BELOW IS INFIX and a leading `/\\` has no left operand, so the bulleted form raised
    ParseError, `tree()` returned None, and `states()` reported "no readable Init" -- for the layout
    Lamport himself writes and every drafter reaches for. Dropping the FIRST bullet is the whole
    transform: `/\\ A` `/\\ B` `/\\ C` becomes `A /\\ B /\\ C`, and every remaining `/\\` is already
    in infix position.

    WHAT THIS COST BEFORE IT WAS FOUND, and it was not only cosmetic. `states()` giving up sets
    `total = 0`; `Claim.vacuous` requires `total > 0`; so `author.preflight`'s vacuity gate -- the
    cheap one, that rejects a claim nothing it ranges over can break -- was silently INACTIVE for
    every module written this way. It failed open, which is the right direction to fail, but it was
    not doing its job and nothing said so. The visible half was a person at the `hitl` checkpoint
    being shown "applies to NONE of the 0 states" for six claims of a property TLC had just found
    to hold.

    FLAT LISTS ONLY, and deliberately. A nested list still fails to parse and is still reported as
    unread, which is the honest answer -- real bulleted lists are indentation-scoped, and a
    transform that guessed at nesting could turn `/\\ A` `/\\ \\/ B` `\\/ C` into something that
    parses and means something else. Failing to read is recoverable; misreading is not.
    """
    stripped = src.strip()
    if not BULLET.match(stripped):
        return src
    return stripped[2:]


def parse(src: str):
    p = Parser(lex(unbullet(src)))
    node = p.expr()
    if p.i != len(p.toks):
        raise ParseError(f"unread input from {p.peek()!r}")
    return node


# ---------------------------------------------------------------------------- the module
DEFINITION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(\(([^)]*)\))?\s*==", re.MULTILINE)
VARIABLES = re.compile(r"^VARIABLES?\s+(.+)$", re.MULTILINE)
INVARIANT_CFG = re.compile(r"^\s*INVARIANTS?\s+(.+?)\s*$", re.MULTILINE)
CONSTANT_CFG = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)\s*$", re.MULTILINE)

# Never a claim: the state machine's own parts, and the type invariant, which is about the model
# rather than about the policy.
MACHINERY = {"Init", "Next", "Spec", "TypeOK", "vars"}

# `Str`, `Num`, `Bool` and `Addr` come from the GENERATED module, which is not on disk when a
# property is being read. They are the tagging discipline the whole vocabulary rests on, so they
# are known here by name rather than resolved.
CONSTRUCTORS = {"Str": 1, "Num": 1, "Bool": 1, "Addr": 4}

# And so do these, which BUILD a session rather than a value. Known here for the same reason and
# one more: a counterexample is a value of the property's own variable -- `gap = 960` -- and the
# only thing that turns that back into something a person recognises is the module's own recipe
# for a session. `Session(960)` is that recipe, and evaluating it needs these.
#
# They mirror `translator/policy_module.py` exactly. The four fields it fills with `Anon` are left
# out: nothing here reads them, and a renderer supplies its own principal and resource anyway.
DECISION_KIND = "request"
EVENT_FIELDS = ("time", "action", "kind", "input", "output")


def event(action, kind, input_, output, time) -> Rec:
    return Rec((("time", time), ("action", action), ("kind", kind),
                ("input", input_), ("output", output)))


@dataclass
class Definition:
    name: str
    params: list[str]
    source: str
    comment: list[str] = field(default_factory=list)

    _parsed: Any = None
    _failed: bool = False

    def tree(self):
        """The parsed body, or None. Parsed once, on demand: most definitions in a module are
        never referenced by a claim, and one that cannot be read must not stop the ones that can."""
        if self._parsed is None and not self._failed:
            try:
                self._parsed = parse(self.source)
            except ParseError:
                self._failed = True
        return self._parsed


class Module:
    """A property module and its .cfg, read together, because neither says what is checked."""

    def __init__(self, tla: str, cfg: str, name: str = ""):
        self.text = tla
        self.cfg = cfg
        self.name = name
        self.defs: dict[str, Definition] = {}
        self._values: dict[str, Any] = {}
        self._read_definitions(tla)

        self.assumed: dict[str, Any] = {}
        self.variables = [v.strip() for m in VARIABLES.findall(tla)
                          for v in m.split(",") if v.strip()]
        self.invariants = [n for line in INVARIANT_CFG.findall(cfg) for n in line.split()]
        self.constants = {m[0]: m[1] for m in CONSTANT_CFG.findall(cfg)}

    # --- reading ------------------------------------------------------------------------------
    def _read_definitions(self, tla: str) -> None:
        lines = strip_block_comments(tla).splitlines()
        starts = [(i, m) for i, l in enumerate(lines) if (m := DEFINITION.match(l))]

        for n, (i, m) in enumerate(starts):
            # To the next definition, a blank line, or the module terminator -- whichever is first.
            # A definition that swallowed the following one would be unparseable, and reported as
            # unread, which is the failure mode worth avoiding here.
            # A continuation is INDENTED. Stopping only at a blank line swallows whatever follows
            # a one-line definition -- `VARIABLE req` on the next line -- and the definition then
            # fails to parse, reported as unreadable when it was perfectly readable.
            stop = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
            end = i + 1
            while end < stop and lines[end].strip() and lines[end][:1].isspace():
                end += 1

            body = "\n".join([lines[i][m.end():]] + lines[i + 1:end])
            params = [p.strip() for p in (m.group(3) or "").split(",") if p.strip()]

            head = i
            source_lines = tla.splitlines()
            while head > 0 and source_lines[head - 1].strip().startswith("\\*"):
                head -= 1

            self.defs[m.group(1)] = Definition(
                m.group(1), params, body,
                [source_lines[j].strip().lstrip("\\*").strip() for j in range(head, i)])

    # --- evaluating ---------------------------------------------------------------------------
    def assuming(self, operator: str, value: Any) -> "Module":
        """This module, with `operator` taken to return `value` whatever its arguments.

        FOR ASKING WHAT A CLAIM DEMANDED. A counterexample says the claim came out false; assuming
        the policy's decision each way and seeing which one does that is how you learn whether the
        claim wanted an allow or a refusal, without having to reason about where in the expression
        the decision sits or how many negations are above it.

        Returns self, so it reads as a modifier. The memo is cleared because a nullary definition
        computed before the assumption would otherwise survive it.
        """
        self.assumed[operator] = value
        self._values.clear()
        return self

    def value(self, name: str) -> Any:
        """The value of a nullary definition, or UNKNOWN. Memoised, and cycle-safe."""
        if name in self._values:
            return self._values[name]
        if name in self.constants:
            raw = self.constants[name]
            return int(raw) if raw.lstrip("-").isdigit() else raw

        d = self.defs.get(name)
        if d is None or d.params or (tree := d.tree()) is None:
            return UNKNOWN

        self._values[name] = UNKNOWN                 # breaks a cycle rather than recursing forever
        self._values[name] = self.evaluate(tree, {})
        return self._values[name]

    def evaluate(self, node, env: dict[str, Any], depth: int = 0) -> Any:
        """A value for `node`, or UNKNOWN.

        UNKNOWN IS THE COMMON CASE AND IS NOT A FAILURE. Any claim worth stating reaches
        `D!Decide`, which is the whole evaluator and is not reimplemented here -- that is TLC's
        job and TLC is about to do it. What this needs to compute is the other half: the domain
        the claim ranges over and the condition that selects within it, both of which are
        ordinary arithmetic over values the module states outright.
        """
        if depth > 60:
            return UNKNOWN

        def ev(n, e=None):
            return self.evaluate(n, env if e is None else e, depth + 1)

        match node:
            case ("num", v) | ("str", v) | ("bool", v):
                return v
            case ("name", n):
                if n in env:
                    return env[n]
                # The generated module's two nullary constants, for the same reason as `Ev`.
                if n == "NoFields" and n not in self.defs:
                    return Rec(())
                if n == "DecisionKind" and n not in self.defs:
                    return DECISION_KIND
                return self.value(n)
            case ("dot", target, fieldname):
                rec = ev(target)
                return rec.get(fieldname) if isinstance(rec, Rec) else UNKNOWN
            case ("app", name, args):
                return self.apply(name, [ev(a) for a in args], args, env, depth)
            case ("un", "~", x):
                v = ev(x)
                return UNKNOWN if not isinstance(v, bool) else (not v)
            case ("bin", op, left, right):
                return self.binary(op, left, right, ev)
            case ("set", items):
                vals = [ev(i) for i in items]
                return UNKNOWN if any(isinstance(v, Unknown) for v in vals) else frozenset(vals)
            case ("seq", items):
                vals = [ev(i) for i in items]
                return UNKNOWN if any(isinstance(v, Unknown) for v in vals) else Seq(tuple(vals))
            case ("rec", fields):
                vals = [(k, ev(v)) for k, v in fields]
                return (UNKNOWN if any(isinstance(v, Unknown) for _, v in vals)
                        else Rec(tuple(vals)))
            case ("comp", body, binds):
                out = set()
                for e in self.bindings(binds, env, depth):
                    v = ev(body, e)
                    if isinstance(v, Unknown):
                        return UNKNOWN
                    out.add(v)
                return frozenset(out)
            case ("filter", var, source, pred):
                src = ev(source)
                if not isinstance(src, frozenset):
                    return UNKNOWN
                out = set()
                for item in src:
                    keep = ev(pred, {**env, var: item})
                    if not isinstance(keep, bool):
                        return UNKNOWN
                    if keep:
                        out.add(item)
                return frozenset(out)
            case ("quant", which, binds, body):
                results = []
                for e in self.bindings(binds, env, depth):
                    v = ev(body, e)
                    if not isinstance(v, bool):
                        return UNKNOWN
                    results.append(v)
                return all(results) if which == "\\A" else any(results)
            case ("case", arms, other):
                for guard, result in arms:
                    g = ev(guard)
                    if not isinstance(g, bool):
                        return UNKNOWN
                    if g:
                        return ev(result)
                return ev(other) if other is not None else UNKNOWN
            case ("ite", cond, then, els):
                c = ev(cond)
                return UNKNOWN if not isinstance(c, bool) else ev(then if c else els)

        return UNKNOWN

    def bindings(self, binds, env: dict[str, Any], depth: int):
        """Every combination of the bound variables, or nothing when a source is not enumerable."""
        combos: list[dict[str, Any]] = [dict(env)]
        for name, source in binds:
            src = self.evaluate(source, env, depth + 1)
            if not isinstance(src, frozenset):
                return []
            combos = [{**c, name: item} for c in combos for item in sorted(src, key=sort_key)]
        return combos

    def apply(self, name: str, values: list[Any], args, env: dict[str, Any], depth: int) -> Any:
        if name in self.assumed:
            return self.assumed[name]

        if name in CONSTRUCTORS:
            if any(isinstance(v, Unknown) for v in values):
                return UNKNOWN
            return Tag(name, values[0] if len(values) == 1 else tuple(values))

        # The session builders, from the generated module. See EVENT_FIELDS above.
        if name == "Ev" and len(values) == 5 and not any(isinstance(v, Unknown) for v in values):
            return event(*values)                    # Ev(action, kind, input, output, time)
        if name == "Request" and len(values) == 2 and not any(isinstance(v, Unknown) for v in values):
            return event(values[0], DECISION_KIND, values[1], Rec(()), 1)

        # `Sequences` and `FiniteSets`, which every property module EXTENDS. Only the handful that
        # turn up in one: `Len(Session(w))` is how a module says "the decision is the last event",
        # which is the commonest shape there is and was unreadable without this.
        if name not in self.defs and (standard := self.standard(name, values)) is not NOTHING:
            return standard

        d = self.defs.get(name)
        if d is None or len(d.params) != len(values) or (tree := d.tree()) is None:
            return UNKNOWN
        return self.evaluate(tree, {**env, **dict(zip(d.params, values))}, depth + 1)

    def standard(self, name: str, values: list[Any]) -> Any:
        """An operator from `Sequences` or `FiniteSets`, or NOTHING if this is not one.

        NOT A LIBRARY, on purpose. These are the ones property modules actually use; anything else
        falls through to UNKNOWN, which is the correct answer for an operator nobody implemented.
        A definition here that guessed would be worse than none.
        """
        if any(isinstance(v, Unknown) for v in values):
            return UNKNOWN

        match (name, values):
            case ("Len", [Seq() as s]):
                return len(s.items)
            case ("Len", [str() as s]):
                return len(s)
            case ("Cardinality", [frozenset() as s]):
                return len(s)
            case ("Head", [Seq(items)]) if items:
                return items[0]
            case ("Tail", [Seq(items)]) if items:
                return Seq(items[1:])
            case ("Append", [Seq(items), x]):
                return Seq(items + (x,))
            case ("SubSeq", [Seq(items), int() as i, int() as j]):
                return Seq(items[max(i, 1) - 1:j])
        return NOTHING

    def binary(self, op: str, left, right, ev) -> Any:
        # Short-circuits first, because a conjunction with one false half is FALSE whatever the
        # other half is -- and the other half is usually the policy decision, which is unknown.
        if op == "/\\":
            l, r = ev(left), ev(right)
            if l is False or r is False:
                return False
            return UNKNOWN if not (isinstance(l, bool) and isinstance(r, bool)) else (l and r)
        if op == "\\/":
            l, r = ev(left), ev(right)
            if l is True or r is True:
                return True
            return UNKNOWN if not (isinstance(l, bool) and isinstance(r, bool)) else (l or r)
        if op == "=>":
            l, r = ev(left), ev(right)
            if l is False or r is True:
                return True
            return UNKNOWN if not (isinstance(l, bool) and isinstance(r, bool)) else ((not l) or r)

        l, r = ev(left), ev(right)
        if isinstance(l, Unknown) or isinstance(r, Unknown):
            return UNKNOWN

        if op == "=":
            return l == r
        if op in ("#", "/="):
            return l != r
        if op == "\\in":
            return (l in r) if isinstance(r, frozenset) else UNKNOWN
        if op == "\\notin":
            return (l not in r) if isinstance(r, frozenset) else UNKNOWN
        if op == "\\subseteq":
            return l <= r if isinstance(l, frozenset) and isinstance(r, frozenset) else UNKNOWN
        if op == "<=>":
            return l == r if isinstance(l, bool) and isinstance(r, bool) else UNKNOWN

        # Arithmetic and ordering are integers only. Comparing a tagged value with `<` is a
        # cross-kind comparison, which the tagging discipline exists to refuse.
        if not (isinstance(l, int) and isinstance(r, int)
                and not isinstance(l, bool) and not isinstance(r, bool)):
            return UNKNOWN
        return {"+": l + r, "-": l - r, "*": l * r, "%": (l % r) if r else UNKNOWN,
                "\\div": (l // r) if r else UNKNOWN,
                "<": l < r, ">": l > r, "<=": l <= r, ">=": l >= r}.get(op, UNKNOWN)

    # --- the state space ----------------------------------------------------------------------
    def states(self) -> tuple[list[dict[str, Any]], str]:
        """Every state the claims will be checked in, and how it was worked out.

        `Init == v \\in S` is the shape every property module here uses, because holding one value
        still is what makes a counterexample NAME the thing that breaks the claim. A different
        shape is reported as unread rather than assumed.
        """
        init = self.defs.get("Init")
        if init is None or (tree := init.tree()) is None:
            return [], "no readable Init"

        binds: list[tuple[str, Any]] = []

        def collect(node) -> bool:
            match node:
                case ("bin", "/\\", l, r):
                    return collect(l) and collect(r)
                case ("bin", "\\in", ("name", var), source):
                    binds.append((var, source))
                    return True
                # `Init == x = 1` -- one state. Not the shape these modules want, because a claim
                # checked in one state is a claim about one state, but it is a shape they get
                # written in, and reading it is how that gets SAID rather than skipped.
                case ("bin", "=", ("name", var), value):
                    binds.append((var, ("set", [value])))
                    return True
            return False

        if not collect(tree):
            return [], f"Init is not `{' /\\ '.join(v + ' \\in ...' for v in self.variables) or 'v \\in S'}`"

        states: list[dict[str, Any]] = [{}]
        for var, source in binds:
            values = self.evaluate(source, {})
            if not isinstance(values, frozenset):
                return [], f"the set `{show(source)}` could not be enumerated"
            states = [{**s, var: v} for s in states for v in sorted(values, key=sort_key)]
        return states, ""


# ---------------------------------------------------------------------------- rendering
def show(node) -> str:
    """The expression as TLA+, near enough to find it in the file."""
    match node:
        case ("num", v):
            return str(v)
        case ("str", v):
            return f'"{v}"'
        case ("bool", v):
            return "TRUE" if v else "FALSE"
        case ("name", n):
            return n
        case ("dot", t, f):
            return f"{show(t)}.{f}"
        case ("app", name, args):
            return f"{name}({', '.join(show(a) for a in args)})"
        case ("un", "~", x):
            return f"~{show(x)}"
        case ("bin", op, l, r):
            return f"{show(l)} {op} {show(r)}"
        case ("set", items):
            return "{" + ", ".join(show(i) for i in items) + "}"
        case ("seq", items):
            return "<<" + ", ".join(show(i) for i in items) + ">>"
        case ("rec", fields):
            return "[" + ", ".join(f"{k} |-> {show(v)}" for k, v in fields) + "]"
        case ("comp", body, binds):
            return ("{" + show(body) + " : "
                    + ", ".join(f"{n} \\in {show(s)}" for n, s in binds) + "}")
        case ("filter", var, source, pred):
            return "{" + f"{var} \\in {show(source)} : {show(pred)}" + "}"
        case ("quant", which, binds, body):
            return (which + " " + ", ".join(f"{n} \\in {show(s)}" for n, s in binds)
                    + f" : {show(body)}")
        case ("case", arms, other):
            return "CASE " + " [] ".join(f"{show(g)} -> {show(r)}" for g, r in arms) + (
                f" [] OTHER -> {show(other)}" if other is not None else "")
        case ("ite", c, t, e):
            return f"IF {show(c)} THEN {show(t)} ELSE {show(e)}"
    return "<unreadable>"


COMPARISONS = {"=": "is", "#": "is not", "/=": "is not", "<": "is less than",
               ">": "is greater than", "<=": "is at most", ">=": "is at least",
               "\\in": "is one of", "\\notin": "is not one of"}

NEGATED = {"=": "is not", "#": "is", "/=": "is", "<": "is at least", ">": "is at most",
           "<=": "is greater than", ">=": "is less than",
           "\\in": "is not one of", "\\notin": "is one of"}


class English:
    """Structure in words, terms as written.

    THE DISCIPLINE THAT MAKES THIS TRUSTWORTHY is that it never paraphrases a term. `req.port`
    stays `req.port` and `Str("external")` becomes `"external"`, because a reviewer checking
    whether the claim says what they meant is checking the terms -- and a fluent renaming of them
    is the one thing that would make a wrong property read as right.
    """

    def __init__(self, module: Module):
        self.m = module

    def decides(self, name: str) -> bool:
        """Does this operator ask the policy for a decision? Then its truth is a grant."""
        d = self.m.defs.get(name)
        return bool(d and "Decide" in d.source)

    def value(self, node) -> str:
        """A term. Evaluated only when that makes it plainer: `10 * Minute` is clearer said both
        ways, `req.port` is not clearer as whatever it happens to be in one state."""
        text = show(node)
        if node[0] in ("num", "str", "name", "dot", "rec"):
            return text

        v = self.m.evaluate(node, {})
        if isinstance(v, Unknown):
            return text

        # A tagged literal is machinery, not content. `Num(22)` said as `Num(22) (= 22)` is the
        # tagging discipline shown to a reviewer who is trying to read the claim, not the model.
        if node[0] == "app" and node[1] in CONSTRUCTORS:
            return show_value(v)
        return f"{text} (= {show_value(v)})"

    def phrase(self, node, negate: bool = False) -> str:
        match node:
            case ("un", "~", inner):
                return self.phrase(inner, not negate)
            case ("bin", "=>", l, r) if not negate:
                return f"if {self.phrase(l)} then {self.phrase(r)}"
            case ("bin", "=>", l, r):
                return f"{self.phrase(l)}, and yet {self.phrase(r, True)}"
            case ("bin", "/\\", l, r):
                joiner = " or " if negate else " and "
                return joiner.join((self.phrase(l, negate), self.phrase(r, negate)))
            case ("bin", "\\/", l, r):
                joiner = " and " if negate else " or "
                return joiner.join((self.phrase(l, negate), self.phrase(r, negate)))
            case ("bin", op, l, r) if op in COMPARISONS:
                table = NEGATED if negate else COMPARISONS
                return f"{self.value(l)} {table[op]} {self.value(r)}"
            case ("app", name, args) if self.decides(name):
                # The whole point of the module, said as the outcome rather than as a truth value.
                which = "REFUSES" if negate else "GRANTS"
                return f"the policy {which} it ({show(('app', name, args))})"
            case ("quant", "\\A", binds, body) if not negate:
                return ("every " + ", ".join(f"{n} in {show(s)}" for n, s in binds)
                        + f" has {self.phrase(body)}")
            case ("quant", "\\E", binds, body) if not negate:
                return ("some " + ", ".join(f"{n} in {show(s)}" for n, s in binds)
                        + f" has {self.phrase(body)}")
            case ("bool", v):
                return "TRUE" if v != negate else "FALSE"

        # Anything this renderer does not model is quoted rather than described. A reviewer can
        # still read TLA+; a confident English sentence about an expression nobody read is the
        # thing they cannot check.
        return f"{show(node)} {'does not hold' if negate else 'holds'}"


# ---------------------------------------------------------------------------- the explanation
@dataclass
class Claim:
    name: str
    defined: bool
    checked: bool
    source: str = ""
    comment: list[str] = field(default_factory=list)
    says: str = ""
    forbids: str = ""
    condition: str = ""                   # the antecedent as TLA+, when the claim has one
    applies: list[str] = field(default_factory=list)     # the states it applies to
    unknown: int = 0                      # states where the condition could not be worked out
    total: int = 0
    settled: int = 0                      # states where the claim is already true, policy unasked
    broken: list[str] = field(default_factory=list)      # ...and where it is already false
    notes: list[str] = field(default_factory=list)

    @property
    def vacuous(self) -> bool:
        """It will be checked, and NO state it ranges over can break it.

        The test is not "its condition never holds" but the stronger one it subsumes: the claim
        comes out TRUE in every state without the policy being consulted at all. That catches both
        shapes of empty property in one measurement -- the guard that selects nothing, and the
        `x = 1` that asserts something about the model rather than about the policy.
        """
        return self.checked and self.defined and self.total > 0 and self.settled == self.total


@dataclass
class Explanation:
    module: str
    claims: list[Claim] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    scope: str = ""                       # how the state space was read, or why it was not
    unchecked: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def vacuous(self) -> list[Claim]:
        return [c for c in self.claims if c.vacuous]


def split_claim(tree):
    """A claim as (condition, outcome). A claim with no `=>` applies everywhere, so no condition."""
    match tree:
        case ("bin", "=>", l, r):
            return l, r
    return None, tree


def explain(module: Module) -> Explanation:
    out = Explanation(module=module.name)
    english = English(module)
    states, why = module.states()
    out.scope = why
    out.states = [", ".join(f"{k} = {show_value(v)}" for k, v in s.items()) for s in states]

    for name in module.invariants:
        d = module.defs.get(name)
        if d is None:
            out.claims.append(Claim(name=name, defined=False, checked=True, notes=[
                f"the .cfg names INVARIANT {name}, but this module does not define it. "
                f"TLC will stop with an error rather than check anything"]))
            continue

        claim = Claim(name=name, defined=True, checked=True,
                      source=" ".join(d.source.split()), comment=d.comment, total=len(states))
        tree = d.tree()
        if tree is None:
            claim.notes.append("this reader could not parse the claim, so it is quoted rather "
                               "than explained. TLC is the parser that matters; this is not it")
            out.claims.append(claim)
            continue

        condition, outcome = split_claim(tree)
        claim.says = (f"whenever {english.phrase(condition)}, then {english.phrase(outcome)}"
                      if condition is not None else f"always: {english.phrase(outcome)}")
        claim.forbids = (f"{english.phrase(condition)}, and yet {english.phrase(outcome, True)}"
                         if condition is not None else english.phrase(outcome, True))

        if condition is not None:
            claim.condition = show(condition)

        for state, shown in zip(states, out.states):
            if condition is None:
                claim.applies.append(shown)
            else:
                held = module.evaluate(condition, state)
                if isinstance(held, Unknown):
                    claim.unknown += 1
                elif held:
                    claim.applies.append(shown)

            # And the claim ENTIRE, in this state. Anything but UNKNOWN here means TLC is about to
            # be asked a question that does not reach the policy: the answer is already fixed by
            # the module's own arithmetic. True everywhere is a property that cannot fail; false
            # anywhere is a counterexample that will be reported as a finding about a policy the
            # run never consulted.
            whole = module.evaluate(tree, state)
            if whole is True:
                claim.settled += 1
            elif whole is False:
                claim.broken.append(shown)

        out.claims.append(claim)

    # Defined, claim-shaped, and not named in the .cfg. Not an error -- checking one claim at a
    # time is a deliberate way to use these modules, because TLC stops at the first violation --
    # but a module whose .cfg names one of five claims is easy to read as a module that checks
    # five, and a green run then covers four claims nobody tested.
    named = set(module.invariants)
    out.unchecked = [n for n, d in module.defs.items()
                     if n not in named and n not in MACHINERY and not d.params
                     and claim_shaped(d)]
    return out


def claim_shaped(d: Definition) -> bool:
    """Does this definition look like an assertion rather than a helper?"""
    tree = d.tree()
    match tree:
        case ("bin", op, _, _) if op in ("=>", "<=>") or op in COMPARISONS:
            return True
        case ("un", "~", _) | ("quant", _, _, _):
            return True
        case ("bin", op, _, _) if op in ("/\\", "\\/"):
            return True
    return False


# ---------------------------------------------------------------------------- output
# 88 and not wider, because `hitl` shows this to a person through a terminal that wraps at 92. A
# line wider than that was wrapped a SECOND time there, keeping only its leading indent, and the
# value column came apart: `hasLoad =` on one line and `FALSE, action = ...` under the label.
WIDTH = 88


def render(x: Explanation, *, width: int = WIDTH) -> str:
    """The reading, laid out for a person: one claim to a block, its label on the left and the
    value in a column of its own, `says` broken at its `then` and `forbids` at its `and yet`, and
    ONE STATE TO A LINE -- a state is itself a comma-separated list, so several on one line gave a
    reader no way to tell where one ended and the next began."""
    lines: list[str] = [f"{x.module}", ""]

    checked = [c for c in x.claims if c.defined]
    over = (f"over {plural(len(x.states), 'state')}:" if x.states
            else f"over an unknown number of states -- {x.scope}.")
    lines.append(f"  {plural(len(checked), 'claim')} will be checked, {over}")
    lines += states(x.states, 8, width, indent=6)
    lines.append("")

    for c in x.claims:
        lines.append(f"  {c.name}")
        for line in c.comment[-3:]:
            if line:
                lines.append(f"      \\* {line}")
        if c.says:
            lines += labelled("says:", c.says, width, breaks=(", then ",))
            lines += labelled("forbids:", c.forbids, width, breaks=(", and yet ",))
        if c.condition:
            if c.applies:
                lines += labelled("applies:", f"to {len(c.applies)} of the "
                                              f"{plural(c.total, 'state')}:", width)
                lines += states(c.applies, 6, width, indent=6 + LABEL + 3)
            elif c.unknown:
                lines += labelled("applies:", f"unknown -- `{c.condition}` could not be worked "
                                              f"out here for {c.unknown} of the {c.total} states",
                                  width)
            elif not c.total:
                # NOT "NONE of the 0 states", which is what this said and which is a STATEMENT OF
                # FACT about a property nobody measured. `states()` returns "no readable Init" when
                # the module's Init is outside the shape it can enumerate -- several variables over
                # named sets rather than one request over a field domain -- and a claim whose state
                # space was never read has not been shown to apply to nothing. It has not been
                # shown to apply to anything either, and those are different sentences.
                #
                # It reached a person at the `hitl` checkpoint reading "applies to NONE of the 0
                # states" on all six claims of a property TLC had just checked and found to hold.
                # The vacuity gate itself was right -- `vacuous` requires `total > 0`, so it failed
                # open -- and only the rendering was wrong, which made it worse rather than better:
                # nothing was blocked, and the reader was told the opposite of the truth.
                lines += labelled("applies:", "NOT DETERMINED -- this module's Init is outside the "
                                              "shape the reader can enumerate, so the states were "
                                              "never counted. This is not a claim that it applies "
                                              "to none of them.", width)
            else:
                lines += labelled("applies:", f"to NONE of the {plural(c.total, 'state')}", width)
        elif c.says and c.total:
            lines += labelled("applies:", f"to all {plural(c.total, 'state')} -- it has no "
                                          f"condition", width)

        if c.vacuous:
            guarded = bool(c.condition) and not c.applies
            why = (f"`{c.condition}` is false in every one of them" if guarded
                   else "it comes out true by the module's own arithmetic")
            fix = ("Widen the set the variable ranges over, or state the claim about values that "
                   "occur in it" if guarded else
                   "As written it asserts something about the MODEL, not about the policy -- the "
                   "policy could say anything at all and this would still hold. State the claim "
                   "in terms of what the policy decides")
            lines += labelled("!!", f"NOTHING THIS CLAIM RANGES OVER CAN BREAK IT: {why}, so it "
                                    f"is already true in all {plural(c.total, 'state')} without "
                                    f"the policy being consulted at all. TLC will report it "
                                    f"holding, having tested nothing. {fix}", width)
        elif c.broken:
            lines += labelled("!!", f"this claim is already FALSE, before the policy is "
                                    f"consulted, in:", width)
            lines += states(c.broken, 3, width, indent=6 + LABEL + 3)
            lines += labelled("", "so TLC will report a violation that says nothing about the "
                                  "policy. Check the claim against the states it ranges over",
                              width)
        for note in c.notes:
            lines += labelled("!!", note, width)
        lines.append("")

    if x.unchecked:
        lines += labelled("!!", f"defined here but NOT named in the .cfg, so not checked: "
                                f"{', '.join(sorted(x.unchecked))}. A claim nobody listed is a "
                                f"claim nobody checked", width, indent=2)
        lines.append("")

    lines.append("  Read the `forbids` lines before the run, not after it. Each one is the only")
    lines.append("  thing its claim can catch; if none of them describes something you would")
    lines.append("  object to, the check will pass without having tested what you meant.")
    return "\n".join(lines)


def plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def listed(items: list[str], most: int) -> str:
    """A few of them, and honest about the rest. A truncated list that does not say it was
    truncated is how "these are the states" becomes a claim about states nobody printed."""
    if len(items) <= most:
        return ", ".join(items)
    return ", ".join(items[:most]) + f", and {len(items) - most} more"


# The label column: the longest label, `forbids:`, and a space.
LABEL = 9


def labelled(label: str, text: str, width: int, indent: int = 6,
             breaks: tuple[str, ...] = ()) -> list[str]:
    """`label  value`, the value wrapped in a column of its own so every continuation lines up
    under it, and the label on the first line only. Each of `breaks` -- `, then `, `, and yet ` --
    starts a new line at its first occurrence, which is where the sentence turns."""
    import textwrap                                                     # noqa: PLC0415

    parts = [text]
    for b in breaks:
        parts = [q for p in parts for q in split_at(p, b)]
    head = " " * indent + (f"{label:<{LABEL}} " if label else " " * (LABEL + 1))
    column = " " * len(head)
    out: list[str] = []
    for part in parts:
        # Hyphens and long words are not break points: a quoted value like "rebalance_portfolio"
        # or a path must survive whole, whatever the column costs.
        out += textwrap.wrap(part, width, initial_indent=head if not out else column,
                             subsequent_indent=column, break_on_hyphens=False,
                             break_long_words=False) or [head.rstrip()]
    return out


def split_at(text: str, sep: str) -> list[str]:
    """`text` broken at the first `sep` (`, then `), the comma kept on the first half and the
    word that turns the sentence starting the second."""
    head, found, tail = text.partition(sep)
    return [head + ",", sep.removeprefix(", ") + tail] if found else [text]


def states(items: list[str], most: int, width: int, indent: int) -> list[str]:
    """One state to a line, each wrapped under itself if it must be, and honest about the rest."""
    import textwrap                                                     # noqa: PLC0415

    pad = " " * indent
    out: list[str] = []
    for item in items[:most]:
        out += textwrap.wrap(item, width, initial_indent=pad, subsequent_indent=pad + "  ",
                             break_on_hyphens=False, break_long_words=False)
    if len(items) > most:
        out.append(f"{pad}and {len(items) - most} more")
    return out


def as_dict(x: Explanation) -> dict:
    return {
        "module": x.module,
        "states": x.states,
        "scope": x.scope or "read from Init",
        "claims": [{"name": c.name, "defined": c.defined, "says": c.says, "forbids": c.forbids,
                    "condition": c.condition, "appliesTo": c.applies, "states": c.total,
                    "unknownIn": c.unknown, "settledWithoutThePolicy": c.settled,
                    "falseWithoutThePolicy": c.broken, "vacuous": c.vacuous, "notes": c.notes}
                   for c in x.claims],
        "definedButNotChecked": sorted(x.unchecked),
        "vacuous": [c.name for c in x.vacuous],
    }


def read(module: Path, cfg: Path | None = None) -> Module:
    config = cfg or module.with_suffix(".cfg")
    return Module(module.read_text(encoding="utf-8"),
                  config.read_text(encoding="utf-8") if config.exists() else "",
                  module.name)


def explain_file(module: Path, cfg: Path | None = None) -> Explanation:
    return explain(read(module, cfg))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("module", type=Path, help="a property module (.tla)")
    ap.add_argument("--cfg", type=Path, default=None,
                    help="its .cfg, if not the module's own name")
    ap.add_argument("--json", action="store_true", help="emit the explanation as JSON")
    args = ap.parse_args()

    if not args.module.exists():
        print(f"no such module: {args.module}", file=sys.stderr)
        return 2

    cfg = args.cfg or args.module.with_suffix(".cfg")
    if not cfg.exists():
        print(f"{args.module.name} has no {cfg.name}, so nothing is checked and there is nothing\n"
              f"to explain. Naming the invariants is deliberate: a claim nobody listed is a\n"
              f"claim nobody checked.", file=sys.stderr)
        return 2

    x = explain_file(args.module, cfg)
    print(json.dumps(as_dict(x), indent=2) if args.json else render(x))

    # A claim that cannot fail is a finding, not a formatting problem, and a caller that gates on
    # this should not have to parse prose to learn it.
    return VACUOUS_CLAIM if x.vacuous else 0


if __name__ == "__main__":
    sys.exit(main())
