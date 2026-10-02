r"""A recursive-descent parser for the modelled subset of Dogwood.

Split out from the differential harness once the grammar stopped being regex-shaped: `&&`, `!`,
parentheses and the infix `since within` nest, and a regex that appears to handle them is the
"silently mishandles a construct" failure this project keeps guarding against.

THE SUBSET, and everything outside it raises `Unsupported`:

    body   := clause+
    clause := ("when" | "unless") ( "temporal" "{" expr "}" | "{" cedar "}" )
    cedar  := cconj ("||" cconj)*          the Cedar level a temporal block sits inside
    cconj  := cunary ("&&" cunary)*
    cunary := "!" cunary | "(" cedar ")" | "temporal" "{" expr "}" | cmp
    expr   := conj
    conj   := unary ("&&" unary)*
    unary  := "!" unary | "(" expr ")" | term
    term   := "formerly" "within" DUR atom
            | "previous" "within" DUR atom
            | [ "!" ] atom "since" "within" DUR atom
    atom   := pred | "tp" "(" IDENT ")" | cmp | "!" atom | "(" atom ("&&" atom)* ")"
    pred   := NS "::Action::" STR "::" IDENT "{" binds "}"
    cmp    := CTX OP LITERAL | LITERAL OP CTX | CTX OP CTX | IDENT OP LITERAL
            | CTX "like" PATTERN
    CTX    := "context.input." IDENT
    bind   := ("input"|"output") "." IDENT ":" rhs
            | ("callerPrincipal"|"callerResource") ":" ("principal"|"resource")
            | "__drupe." IDENT ":" rhs
    rhs    := "context.input." IDENT | "true" | "false" | STR | INT
            | "decimal" "(" STR ")" | NS "::" IDENT "::" STR | IDENT | "_"

Aggregations are covered in the one shape the corpus actually uses:

    exists (n: T). ((count for (t: Timepoint). where (phi)) == n && n >= 3)

with the parentheses around `phi` optional -- `where phi` is the same thing -- and the whole
comparison writable four ways, all normalised to `AGG CMP k`:

    exists (n: T). ((AGG) == n && n > 0)     (AGG) > 0     AGG > 0     0 < AGG

`exists` also carries its general meaning, not only that idiom: `exists (u: String). C` quantifies
`u` over the value domain and is true when some assignment makes `C` hold. That needed no new
evaluation -- the machinery enumerating an aggregate's satisfying assignments already answers it.

`phi` is either a temporal term or -- with NO temporal operator anywhere in it -- a bare
conjunction of atoms, which means "at the decision's own timepoint". An unwrapped aggregate counts
what is happening now rather than what has happened. A bare predicate at the TOP level of a
`when temporal` block means the same thing, which the built engine was asked directly rather than
inferred: one naming an action the decision is not denies, even with such an event in the trace. The two are told apart by looking for a
temporal keyword in the body, not by parsing and backtracking: a failure inside the temporal
reading can mean "this is the bare form" or "this uses something unsupported", and catching it
would conflate them.

which says nothing more than `count(...) >= 3`. That exact shape is recognised; any other use of
`exists` is REFUSED rather than approximated, because general existential quantification over a
value domain is a different thing and pretending otherwise is guessing.

`cmp` reads the DECISION event, not the candidate one, so it evaluates the same at every
candidate index -- it filters the request rather than the history, and appears inside a group only
because that is where an author writes it. Only a literal right-hand side is accepted; the corpus
also contains `context.input.amount > context.input.limit`, an enum entity
(`Drupe::Grant_Input_role::"o'admin"`) and a comparison to a bound variable, and those are three
further features rather than three spellings of this one.

MACROS are expanded before parsing -- see `expand_macros`. `def temporal once(?w, ?s) { ... };`
and `def cedar is_small(?n) { ... };`, declared inline or in a `macros.dw` beside the policy, with
`?p` spliced literally and `$t` gensymmed per expansion. The INJECTION operator comes with them:
`?s{ input.status: "approved" }` refines whatever predicate the caller passed, forcing a field onto
an event the caller never mentioned.

CEDAR'S `like` is modelled on a context field, and the PATTERN IS EVALUATED BY TLC, not here. A
TLA+ string is a sequence and TLC's `Sequences` handles `Len`, `\o` and `SubSeq` on one; what it
does not support is applying a string as a function, so `s[1]` fails and a character is read as
`SubSeq(s, i, i)`. `LikeMatches` in `DogwoodSemantics.tla` is the matcher.

`like_matches` below is therefore NOT the semantics -- it exists only to synthesise witness values
for the vacuity checker's invented domains, where a candidate that is wrong can lose a witness but
can never make a policy falsely live, because TLC still judges it.

Still refused: information providers (`Lists::Allowed(...)` and friends -- sandboxed Rhai scripts,
so a verdict is not a function of the policy and the trace at all, and REFUSING IS THE CORRECT
ANSWER rather than a gap), `if`/`then`/`else`, Cedar's `has` / `in` / `is`, `like` anywhere but on
a context field, a `when`
clause tagged with anything but `temporal`, nested temporal operators (`formerly` inside
`formerly`), a constrained `principal` or `resource` scope, `null` values, non-ASCII field values
(a TLA+ string literal cannot carry one), deep paths under `__drupe` beyond a single leaf, and
`Long` values outside TLC's integer range -- the last of which no amount of modelling will fix.
"""

from __future__ import annotations

import re

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# How far back any `within` may look when the event schema does not say. The language's own
# default, not ours -- a schema raises it with `max_window = 30d` or lowers it to tighten what
# policies may do. The bound is INCLUSIVE: `within 24h` passes, `within 48h` does not.
DEFAULT_MAX_WINDOW = 24 * 3600

# Reading a comparison backwards: `100 < x` says what `x > 100` says.
FLIP = {">": "<", "<": ">", ">=": "<=", "<=": ">=", "==": "==", "!=": "!="}

DECIMAL_SCALE = 10 ** 4


class Dec(int):
    """A Cedar decimal, carried as its value scaled by 10^4.

    An int subclass, so it travels the same paths as a Long -- but checked before `int` wherever
    a kind is decided, so a decimal never silently becomes one and never compares equal to a Long
    that happens to share the scaled value.
    """


def parse_decimal(text: str) -> Dec:
    """`"0.50"` -> Dec(5000). Refuses more precision than Cedar allows rather than rounding."""
    sign = -1 if text.startswith("-") else 1
    whole, _, frac = text.lstrip("+-").partition(".")
    if len(frac) > 4:
        raise Unsupported(f"decimal {text!r} has more than four fractional digits")
    return Dec(sign * (int(whole or 0) * DECIMAL_SCALE + int((frac or "0").ljust(4, "0"))))

# `context.system.now.toTime()` -- the wall-clock TIME OF DAY at the moment of the decision,
# which is how a "business hours only" policy is written. It is modelled as an ordinary request
# field because that is what it is: a per-decision value the policy reads and cannot influence.
# Nothing in the trace determines it, so the domain has to make both "inside the window" and
# "outside" reachable, which is exactly what a field domain already does.
#
# The name has to be a valid TLA+ identifier, because field names become record field names in the
# generated module -- so it cannot be `system.now`. A policy that happens to read an input field of
# this name is refused rather than silently conflated; see `vocabulary`.
SYSTEM_NOW = "systemNowTime"

# Cedar counts a duration in MILLISECONDS, and so does this: `toTime()` returns milliseconds since
# midnight, `duration("9h")` is 32400000, and comparing them is comparing like with like. Seconds
# would have been tidier and would have silently truncated `500ms`.
DURATION_UNITS = {"ms": 1, "s": 1000, "m": 60 * 1000, "h": 3600 * 1000, "d": 86400 * 1000}
DAY_MS = DURATION_UNITS["d"]
DURATION_PART = re.compile(r"(\d+)(ms|[smhd])")

# Cedar's duration-to-Long methods, by the milliseconds in one unit. `toTime().toHours()` is the
# time of day in WHOLE hours: Cedar truncates, and since a time of day is never negative that is
# the floor, so `toHours() OP k` is exactly a comparison of the milliseconds against `k` hours.
DURATION_METHODS = {"toMilliseconds": DURATION_UNITS["ms"], "toSeconds": DURATION_UNITS["s"],
                    "toMinutes": DURATION_UNITS["m"], "toHours": DURATION_UNITS["h"],
                    "toDays": DURATION_UNITS["d"]}


def parse_duration(text: str) -> int:
    """`"1h30m"` -> 5400000. Cedar's duration literal, in milliseconds.

    Refuses anything it cannot read rather than reading part of it: a duration parsed as half its
    value is a policy checked at the wrong threshold, which no verdict would reveal.
    """
    body = text.lstrip("+-")
    if not body or not DURATION_PART.fullmatch(body) and not DURATION_PART.match(body):
        raise Unsupported(f"duration {text!r} is not a Cedar duration literal")

    total, seen = 0, 0
    for m in DURATION_PART.finditer(body):
        if m.start() != seen:
            raise Unsupported(f"duration {text!r} has an unreadable part at {body[seen:]!r}")
        total += int(m.group(1)) * DURATION_UNITS[m.group(2)]
        seen = m.end()
    if seen != len(body):
        raise Unsupported(f"duration {text!r} has an unreadable part at {body[seen:]!r}")

    return bounded(-total if text.startswith("-") else total, "a duration the policy compares against")


# A `like` pattern is a list whose items are single characters, or WILDCARD for `*`.
WILDCARD = None

# Every escape Cedar's string grammar defines. `\*` is handled separately: it is the one escape
# that is NOT a string escape -- Cedar's escaper reports it as invalid and the pattern layer
# reinterprets it as a literal asterisk.
PATTERN_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0",
                   "\\": "\\", '"': '"', "'": "'"}


IP_METHODS_UNARY = ("isIpv4", "isIpv6", "isLoopback", "isMulticast")


def parse_cidr(text: str) -> tuple[list[int], int]:
    """`"10.0.0.0/8"` -> ([10, 0, 0, 0], 8). A bare address is its own /32.

    Octets rather than a 32-bit number: TLC works in Java ints and stops at 2147483647, so
    `208.4.4.0` -- 3489924096 -- is not representable. Every octet is 0..255.
    """
    addr, _, prefix = text.partition("/")
    if ":" in addr:
        raise Unsupported(f"IPv6 address {text!r}, which is not modelled -- eight groups and a "
                          f"different parse from the four octets modelled here")

    parts = addr.split(".")
    if len(parts) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in parts):
        raise Unsupported(f"{text!r} is not a dotted-quad IPv4 address")

    bits = int(prefix) if prefix else 32
    if not prefix.isdigit() and prefix:
        raise Unsupported(f"prefix length {prefix!r} in {text!r} is not a number")
    if not 0 <= bits <= 32:
        raise Unsupported(f"prefix length /{bits} in {text!r} is outside 0..32")

    return [int(o) for o in parts], bits


def parse_like_pattern(body: str) -> list:
    """The body of a `like` string literal, quotes stripped and escapes intact."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "*":
            out.append(WILDCARD)
            i += 1
        elif c != "\\":
            out.append(c)
            i += 1
        elif i + 1 >= len(body):
            raise Unsupported("a `like` pattern ends in a backslash")
        elif body[i + 1] == "*":
            out.append("*")            # the literal asterisk
            i += 2
        elif body[i + 1] in PATTERN_ESCAPES:
            out.append(PATTERN_ESCAPES[body[i + 1]])
            i += 2
        else:
            # `\x41`, `\u{1F600}`: real Cedar, simply not modelled. Saying so beats guessing.
            raise Unsupported(f"escape '\\{body[i + 1]}' in a `like` pattern is not modelled")
    return out


def like_matches(pattern: list, text: str) -> bool:
    """Does `text` match the pattern? `*` is the only metacharacter, so a regex is exact."""
    rx = "".join(".*" if e is WILDCARD else re.escape(e) for e in pattern)
    return re.fullmatch(rx, text, re.DOTALL) is not None


def pattern_witnesses(pattern: list) -> tuple[str, str | None]:
    """One string the pattern matches and one it does not, for a synthesised value domain.

    Without a matching witness a `like` guard can never be true, and everything behind it would
    be reported vacuous when it is not. The non-matching one is what makes "the guard failed"
    reachable. A pattern of nothing but wildcards matches everything, so it HAS no second
    witness; the caller is told with None rather than handed a wrong one.
    """
    hit = "".join("" if e is WILDCARD else e for e in pattern)
    for miss in ("\u0000none", "\u0000" + hit, hit + "\u0000", "zz" + hit):
        if not like_matches(pattern, miss):
            return hit, miss
    return hit, None


# `count` and `sum` bring binders, `exists` and `tp(...)`; a bare identifier bind value is a
# pattern variable that only has meaning inside one. All refused together.
AGGREGATIONS = ("count ", "sum ", "exists ", "tp(")

TOKEN = re.compile(r"""
      (?P<str>"[^"]*")
    | (?P<dur>\d+[smhd]\b)
    | (?P<int>\d+)
    | (?P<param>\?[A-Za-z_][A-Za-z0-9_]*)
    | (?P<binder>\$[A-Za-z_][A-Za-z0-9_]*)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<sym>::|&&|\|\||<=|>=|!=|==|[!(){}\[\]:.,<>=+?$*-])
    | (?P<ws>\s+)
""", re.X)


class Unsupported(Exception):
    """The policy uses a construct outside the modelled subset.

    `kind` is the coarse label to TALLY on, where the message names the specific thing. Once a
    message interpolates a provider or macro name, counting messages puts every name in its own
    bucket and a summary stops summarising. Defaults to the message, so a raise site that names
    nothing needs no kind.
    """

    def __init__(self, message: str, kind: str | None = None):
        super().__init__(message)
        self.kind = kind or message


def tokenize(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m:
            raise Unsupported(f"unlexable at {text[i:i + 24]!r}")
        if not m.group("ws"):
            out.append(m.group(0))
        i = m.end()
    return out


class Parser:
    def __init__(self, tokens: list[str], max_window: int | None = DEFAULT_MAX_WINDOW):
        self.t = tokens
        self.i = 0
        self.max_window = max_window

    # -- token helpers ---------------------------------------------------------
    def peek(self, n: int = 0) -> str | None:
        return self.t[self.i + n] if self.i + n < len(self.t) else None

    def take(self) -> str:
        if self.i >= len(self.t):
            raise Unsupported("unexpected end of policy")
        self.i += 1
        return self.t[self.i - 1]

    def expect(self, tok: str) -> str:
        got = self.take()
        if got != tok:
            raise Unsupported(f"expected {tok!r}, got {got!r}")
        return got

    def accept(self, tok: str) -> bool:
        if self.peek() == tok:
            self.i += 1
            return True
        return False

    # -- grammar ---------------------------------------------------------------
    def expr(self) -> dict:
        parts = [self.unary()]
        while self.accept("&&"):
            parts.append(self.unary())
        if self.peek() == "||":
            raise Unsupported("disjunction between temporal terms")
        return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

    def binders(self) -> list[dict]:
        """`for (t: Timepoint), (x: String).`"""
        self.expect("for")
        out = []
        while True:
            self.expect("(")
            name = self.take()
            self.expect(":")
            ty = self.take()
            while self.accept("::"):
                ty = self.take()
            self.expect(")")
            out.append({"name": name, "type": ty})
            if not self.accept(","):
                break
        self.expect(".")
        return out

    def aggregate(self) -> dict:
        """`count for (...). where (C)` or `sum v for (...). where (C)`.

        Inside the body -- and ONLY there -- a bare predicate with no temporal operator is
        allowed, and means "at the decision's own timepoint". The flag is scoped to this call
        because that is where the corpus evidence is: a bare predicate at the top level of a
        `when temporal` block is a different question, with nothing to check an answer against.
        """
        kind = self.take()
        over = "" if kind == "count" else self.take()
        bs = self.binders()
        self.expect("where")
        # Optional: `where (phi)` and `where phi` are the same thing, and the corpus writes both.
        parens = self.accept("(")

        if self.body_has_temporal():
            cond = self.expr()
        else:
            # No temporal operator anywhere in the body: it sees only the decision's own
            # timepoint, so the conjuncts are ATOMS and the whole thing becomes one `at` term.
            # Window 0 is a placeholder; the `at` arm of TermHolds never reads it.
            at = self.atom_conj()
            cond = {"op": "term",
                    "term": {"op": "at", "window": 0, "atom": at, "left": at, "leftNeg": False}}

        if parens:
            self.expect(")")
        return {"kind": kind, "over": over, "binders": bs, "cond": cond}

    def atom_conj(self) -> dict:
        """`atom ("&&" atom)*`, unparenthesised -- the shape an unwrapped body has."""
        parts = [self.atom()]
        while self.accept("&&"):
            parts.append(self.atom())
        return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

    def body_has_temporal(self) -> bool:
        """Does a temporal operator appear before the `)` that closes the body?

        Includes nested ones. A `since` inside a group is still outside the modelled subset, and
        routing such a body to `expr()` keeps it REFUSED rather than silently reading it as the
        bare form -- which would be a wrong answer rather than an absent one.
        """
        depth, j = 0, self.i
        while j < len(self.t):
            tok = self.t[j]
            if tok == "(":
                depth += 1
            elif tok == ")":
                if depth == 0:
                    return False
                depth -= 1
            elif tok in ("formerly", "previous", "since"):
                return True
            j += 1
        raise Unsupported("unbalanced parentheses in an aggregate body")

    def exists_idiom(self) -> dict:
        """`exists (n: T). ((AGG) == n && n CMP k)` -- the corpus's only use of `exists`.

        Recognised as exactly `AGG CMP k`. Anything else about `exists` is refused: general
        quantification over a value domain is a different thing from this shape.
        """
        self.expect("exists")
        self.expect("(")
        var = self.take()
        self.expect(":")
        ty = self.take()
        while self.accept("::"):
            ty = self.take()
        self.expect(")")
        self.expect(".")

        # `exists (n: T). ((AGG) == n && ...)` is the idiom; anything else is a real
        # existential over the value domain, and is read as one rather than refused.
        #
        # The idiom comes in two wrappings. The corpus and Dogwood's guide parenthesise the whole
        # body; every aggregate in AgentCore's guide leaves it bare -- `exists (n: Long). (AGG)
        # == n && n > 3` -- which is legal because an `exists` scope is greedy to the right.
        # Both mean `AGG CMP k`. Refusing the bare one refused all six of AWS's aggregates.
        wrapped = self.peek() == "(" and self.peek(1) == "(" and self.peek(2) in ("count", "sum")
        bare = self.peek() == "(" and self.peek(1) in ("count", "sum")
        if not (wrapped or bare):
            body = self.group() if self.peek() == "(" else self.expr()
            return {"op": "exists",
                    "agg": {"kind": "exists", "over": "",
                            "binders": [{"name": var, "type": ty}], "cond": body}}

        if wrapped:
            self.expect("(")
        self.expect("(")
        agg = self.aggregate()
        self.expect(")")
        if self.take() != "==":
            raise Unsupported("exists body is not `AGG == v && v CMP k`")
        if self.take() != var:
            raise Unsupported("exists binds a variable the aggregate is not compared to")
        self.expect("&&")
        if self.take() != var:
            raise Unsupported("exists comparison does not start from the bound variable")
        cmp_op = self.comparison_op()
        value = self.integer_bound()
        if wrapped:
            self.expect(")")
        return {"op": "agg", "agg": agg, "cmp": cmp_op, "value": value}

    def integer_bound(self) -> int:
        """The count or total an aggregate is compared against."""
        neg = self.accept("-")
        tok = self.take()
        if not re.fullmatch(r"\d+", tok):
            raise Unsupported(f"comparison bound {tok!r} is not an integer")
        return bounded(-int(tok) if neg else int(tok), "an aggregate's comparison bound")

    def unary(self) -> dict:
        if self.peek() == "exists":
            return self.exists_idiom()

        # `tp(t)` conjoined with a temporal TERM rather than sitting inside an atom group:
        # `(A since within 1h B) && tp(t)`. Outside a group there is no candidate event to bind
        # to, so it binds the decision's own timepoint -- which is what an `at` term evaluates
        # against, so this needs no semantics of its own.
        if self.peek() == "tp":
            at = self.atom()
            return {"op": "term",
                    "term": {"op": "at", "window": 0, "atom": at,
                             "left": at, "leftNeg": False}}

        # An aggregate compared directly, rather than wrapped in the exists idiom that says the
        # same thing. Parenthesised or not, and with either side written first.
        if self.starts_aggregate():
            return self.agg_comparison()
        if self.peek() == "!" and self.peek(1) == "exists":
            self.take()
            return {"op": "not", "args": [self.exists_idiom()]}

        if self.peek() == "!":
            # `!A since within W B` negates the LEFT OPERAND of the since, not the whole
            # term, so a bare predicate after `!` has to be looked past before deciding.
            save = self.i
            self.take()
            # `!(A) since ...` is the same thing with the operand parenthesised, and it reads
            # identically up to the closing paren. Look past it before committing: if a `since`
            # follows, this is a negated since-left, not a negation of a group.
            if self.peek() == "(" and self.after_group() != "since":
                return {"op": "not", "args": [self.group()]}
            self.i = save
            return self.term()
        # A group followed by `since` is that operator's LEFT OPERAND, not a condition of its
        # own: `(A && context.input.amount > 0) since within 1h B`. Same lookahead as the
        # negated form above.
        if self.peek() == "(":
            if self.after_group() == "since":
                return self.term()
            return self.group()
        return self.term()

    def after_group(self) -> str | None:
        """The token following the `(`...`)` starting at the cursor, without consuming anything."""
        depth, j = 0, self.i
        while j < len(self.t):
            if self.t[j] == "(":
                depth += 1
            elif self.t[j] == ")":
                depth -= 1
                if depth == 0:
                    return self.t[j + 1] if j + 1 < len(self.t) else None
            j += 1
        raise Unsupported("unbalanced parentheses")

    def starts_aggregate(self) -> bool:
        """Does an aggregate comparison begin here, however it is written?"""
        if self.peek() in ("count", "sum"):
            return True
        if self.peek() == "(" and self.peek(1) in ("count", "sum"):
            return True
        # `0 < count ...` -- the bound written first.
        return (self.peek(1) in ("==", "!=", ">=", "<=", ">", "<")
                and (self.peek(2) in ("count", "sum")
                     or (self.peek(2) == "(" and self.peek(3) in ("count", "sum"))))

    def bare_or_parenthesised_agg(self) -> dict:
        if self.accept("("):
            agg = self.aggregate()
            self.expect(")")
            return agg
        return self.aggregate()

    def agg_comparison(self) -> dict:
        """`AGG CMP k`, normalising `k CMP AGG` into it."""
        if self.peek() in ("count", "sum") or self.peek() == "(":
            agg = self.bare_or_parenthesised_agg()
            return {"op": "agg", "agg": agg, "cmp": self.comparison_op(),
                    "value": self.integer_bound()}

        value = self.integer_bound()
        op = FLIP[self.comparison_op()]
        return {"op": "agg", "agg": self.bare_or_parenthesised_agg(), "cmp": op, "value": value}

    # -- the Cedar level ------------------------------------------------------
    def body(self) -> dict:
        """`when { E }`, `when temporal { E }`, and any `unless` clause after them."""
        parts = []
        while self.peek() in ("when", "unless"):
            keyword = self.take()
            clause = self.clause()
            parts.append({"op": "not", "args": [clause]} if keyword == "unless" else clause)

        if not parts:
            raise Unsupported(f"policy body starts with {self.peek()!r}, not when/unless")
        return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

    def clause(self) -> dict:
        # `when temporal { ... }` -- the whole clause is one temporal block.
        if self.peek() == "temporal":
            self.take()
            self.expect("{")
            inner = self.expr()
            self.expect("}")
            return inner

        # `when guardrails { E }` IS `when { E }`. The language guide is explicit that the tag
        # carries no semantics and is "retained only for surface compatibility" -- an information
        # provider is an ordinary Cedar call and works in a bare `when` too. So the tag is dropped
        # and the body parsed as Cedar; whatever is inside stands or falls on its own.
        if self.peek() == "guardrails":
            self.take()

        # Any OTHER named clause is a form we have not seen and will not guess at.
        if self.peek() != "{" and self.peek(1) == "{":
            raise Unsupported(
                f"policy uses a `when {self.peek()}` clause, which is not modelled",
                "uses a named `when` clause other than temporal")

        self.expect("{")
        inner = self.cedar_expr()
        self.expect("}")
        return inner

    def cedar_expr(self) -> dict:
        parts = [self.cedar_conj()]
        while self.accept("||"):
            parts.append(self.cedar_conj())
        return parts[0] if len(parts) == 1 else {"op": "or", "args": parts}

    def cedar_conj(self) -> dict:
        parts = [self.cedar_unary()]
        while self.accept("&&"):
            parts.append(self.cedar_unary())
        return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

    def cedar_unary(self) -> dict:
        # `if C then A else B` is `(C && A) || (!C && B)`. Both branches are boolean here, so the
        # identity is exact; desugaring keeps the condition vocabulary the model checks unchanged.
        if self.peek() == "if":
            self.take()
            cond = self.cedar_expr()
            self.expect("then")
            yes = self.cedar_expr()
            self.expect("else")
            no = self.cedar_expr()
            return {"op": "or", "args": [
                {"op": "and", "args": [cond, yes]},
                {"op": "and", "args": [{"op": "not", "args": [cond]}, no]},
            ]}

        if self.peek() == "!":
            self.take()
            return {"op": "not", "args": [self.cedar_unary()]}
        if self.peek() == "(":
            self.take()
            inner = self.cedar_expr()
            self.expect(")")
            return inner

        # A temporal block sitting inside a Cedar condition, as one operand of it.
        if self.peek() == "temporal":
            self.take()
            self.expect("{")
            inner = self.expr()
            self.expect("}")
            return inner

        self.reject_unmodelled_cedar()

        # `context.input.src.isInRange(ip("10.0.0.0/8"))` -- Cedar's ipaddr extension. Only this
        # way round: a constant receiver decides nothing about the request.
        if self.peek() == "context" and self.ip_method_ahead():
            at = self.ip_test()
            return {"op": "term",
                    "term": {"op": "at", "window": 0, "atom": at, "left": at, "leftNeg": False}}

        # Otherwise a comparison on the request. Wrapped in an `at` term so the condition level
        # stays one shape; `cmp` reads only `dec`, so the index the wrapper supplies is unused.
        at = self.comparison()
        return {"op": "term",
                "term": {"op": "at", "window": 0, "atom": at, "left": at, "leftNeg": False}}

    def reject_unmodelled_cedar(self) -> None:
        """Name the Cedar feature, when the next thing is one we do not model.

        Called where a predicate or a comparison is expected -- the two places a policy reaches
        for something outside the subset. Every message below was read off the example that
        produces it; see the module header for why that mattered.
        """
        head, nxt = self.peek(), self.peek(1)

        if nxt == "::":
            # Walk the `::` chain. `Lists::Allowed(...)` is an information provider -- a
            # sandboxed Rhai script, so its result is a function of neither the policy nor the
            # trace and nothing here could predict it. `Drupe::Action::"Read"::response{...}`
            # has the same shape up to the last token and IS modelled, so the two are told apart
            # by what follows the chain: a call is a provider, a brace is a predicate.
            parts, j = [head], 1
            while self.peek(j) == "::":
                parts.append(self.peek(j + 1) or "")
                j += 2
            if self.peek(j) == "(":
                raise Unsupported(
                    f"policy calls the information provider {'::'.join(parts)}, which runs a "
                    f"script -- its result is not a function of the policy or the trace",
                    "calls an information provider (a Rhai script)")
            return

        # `ip("1.2.3.4").isInRange(...)` -- a constant receiver. The guide gives this form, and
        # it is a fixed truth value: it says nothing about the request, so a policy gated on one
        # is either always or never subject to that clause.
        if head == "ip" and nxt == "(":
            raise Unsupported(
                "policy calls `isInRange` on an `ip(...)` literal rather than on a request field; "
                "a constant receiver decides nothing about the request",
                "uses ipaddr on a constant receiver")

        # `recently_logged_in(context.input.user)` -- a macro declared by `def temporal` at the
        # top of the same file, or one reached through `call`. Expanding it is a purely
        # syntactic job we have not done, which is a better thing to be told than that a
        # namespace separator was missing.
        if nxt == "(" and head and re.fullmatch(r"[A-Za-z_]\w*", head) and head != "decimal":
            raise Unsupported(
                f"policy calls {head}(), which is not defined as a macro in this policy or its "
                f"macros file -- an information provider, or a definition we were not given",
                "calls something undefined -- a provider or an absent macro")

    def group(self) -> dict:
        self.expect("(")
        inner = self.expr()
        self.expect(")")
        return inner

    def term(self) -> dict:
        head = self.peek()

        if head in ("formerly", "previous"):
            self.take()
            self.expect("within")
            window = self.duration(self.take())
            at = self.atom()
            return {"op": "term",
                    "term": {"op": head, "window": window, "atom": at,
                             "left": at, "leftNeg": False}}

        # Otherwise the only remaining form is an infix `since`. Its left operand may be
        # parenthesised -- `!(A) since ...` -- which changes nothing about its meaning.
        neg = self.accept("!")
        # An atom, like the right operand: a predicate, a group, a comparison. `!(A) since ...`
        # negates that operand rather than the whole term.
        left = self.atom()

        # No `since` after it, so this is a BARE predicate: an anti-join at the decision's own
        # timepoint rather than anything about history. The engine settles the reading -- a bare
        # predicate naming an action the decision is not denies, even when the trace contains one.
        # Same `at` shape the unwrapped-aggregate body uses.
        if self.peek() != "since":
            at = {"op": "not", "args": [left]} if neg else left
            return {"op": "term",
                    "term": {"op": "at", "window": 0, "atom": at,
                             "left": at, "leftNeg": False}}
        self.take()
        self.expect("within")
        window = self.duration(self.take())
        right = self.atom()
        return {"op": "term",
                "term": {"op": "since", "window": window, "atom": right,
                         "left": left, "leftNeg": neg}}

    def atom(self) -> dict:
        """What a temporal operator scopes over: a predicate, a `tp(v)`, or a group of both.

        An atom is evaluated AT A CANDIDATE EVENT rather than at the decision point, which is
        how `tp(t)` gets to bind `t` to the index of whatever the enclosing `formerly` found.
        """
        if self.peek() == "(":
            self.expect("(")
            parts = [self.atom()]
            while self.accept("&&"):
                parts.append(self.atom())
            self.expect(")")
            return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

        # `!(B)` inside a group -- "this happened and that did not".
        if self.peek() == "!":
            self.take()
            return {"op": "not", "args": [self.atom()]}

        if self.peek() == "tp":
            self.take()
            self.expect("(")
            var = self.take()
            self.expect(")")
            return {"op": "tp", "var": var}

        # A comparison, written with either side first: `context.input.x > 100` or `100 < context.input.x`.
        if self.peek() == "context" or self.peek(1) in ("==", "!=", ">=", "<=", ">", "<"):
            return self.comparison()

        self.reject_unmodelled_cedar()
        return {"op": "pred", "pred": self.pred()}

    def comparison(self) -> dict:
        """`context.input.FIELD OP <literal>` -- a filter on the request, not on the history.

        It reads the decision event, so its value is the same at every candidate index. Only a
        literal right-hand side is accepted; see the module header for what is refused and why.
        """
        # Either side may carry the literal. `100 < context.input.amount` says what
        # `context.input.amount > 100` says, so it is flipped into that form rather than
        # modelled twice.
        # A bound variable rather than a request field: `a > 0`, narrowing which bindings the
        # enclosing count/sum takes in.
        if self.peek() != "context" and re.fullmatch(r"[A-Za-z_]\w*", self.peek() or ""):
            var = self.take()
            return {"op": "cmpvar", "var": var, "cmp": self.comparison_op(),
                    "value": self.literal()}

        if self.peek() == "context":
            field = self.context_field()
            unit = self.duration_method(field)

            # `context.input.stock like "A*"`. Only this way round: Cedar's `like` takes the
            # string on the left and a pattern LITERAL on the right, never an expression.
            if self.peek() == "like":
                self.take()
                tok = self.take()
                if not tok.startswith('"'):
                    raise Unsupported(f"`like` pattern {tok!r} is not a string literal")
                return {"op": "like", "field": field,
                        "pattern": parse_like_pattern(tok[1:-1])}

            op = self.comparison_op()

            if self.peek() == "context":
                # Two fields and no literal: `context.input.amount > context.input.limit`,
                # a comparison between two parts of the SAME request.
                if unit:
                    raise Unsupported(f"policy compares context.system.now.toTime() converted to "
                                      f"an integer against another field, which is not modelled "
                                      f"-- only against an integer literal")
                return {"op": "cmp2", "field": field, "cmp": op,
                        "other": self.context_field()}
            is_duration = self.peek() == "duration"
            value = self.literal()
        else:
            is_duration = self.peek() == "duration"
            value = self.literal()
            op = FLIP[self.comparison_op()]
            field = self.context_field()
            unit = self.duration_method(field)

        if unit:
            if is_duration:
                # `literal()` hands a duration back as milliseconds, which would otherwise be
                # compared as a count of hours -- and land as an overflow nobody could place.
                raise Unsupported("policy compares an integer from a duration conversion "
                                  "(`.toHours()` and the like) against a `duration(...)` literal; "
                                  "Cedar rejects that as a type error, Long against duration")
            return self.scaled_time(op, value, unit)

        if field == SYSTEM_NOW and isinstance(value, int) and not isinstance(value, bool):
            # Every bound past the end of the day compares the same as the end of the day, and one
            # written in days -- `duration("1000d")` -- would not fit in TLC's integers otherwise.
            value = min(max(value, -1), DAY_MS)

        if not isinstance(value, int) or isinstance(value, bool):
            if op not in ("==", "!="):
                raise Unsupported(f"operator {op!r} on a non-numeric value")

        return {"op": "cmp", "field": field, "cmp": op, "value": value}

    def duration_method(self, field: str) -> int | None:
        """The unit of a `.toHours()`-style conversion after `context.system.now.toTime()`, if any.

        `None` when there is none, which leaves the time of day as a duration in milliseconds --
        compared against a `duration("9h")` literal. A method on any OTHER context field is refused
        by name here rather than reaching `comparison_op` as an operator called `.`.
        """
        if self.peek() != ".":
            return None
        method = self.peek(1)
        if field == SYSTEM_NOW and method in DURATION_METHODS:
            self.take()
            self.take()
            self.expect("(")
            self.expect(")")
            return DURATION_METHODS[method]
        if field == SYSTEM_NOW:
            raise Unsupported(
                f"policy calls context.system.now.toTime().{method}(), which is not modelled -- "
                f"only the duration-to-integer conversions are: "
                f"{', '.join(f'.{m}()' for m in DURATION_METHODS)}",
                "uses a method on the wall clock we do not model")
        raise Unsupported(f"policy calls `.{method}()` on context.input.{field}, which is not "
                          f"modelled", "uses a method on a context field we do not model")

    def scaled_time(self, op: str, value, unit: int) -> dict:
        """`context.system.now.toTime().toHours() OP k`, as a comparison on milliseconds.

        The method truncates, so each comparison against `k` units becomes one against a
        millisecond boundary: `toHours() > 9` is "10:00 or later", not "after 09:00". Equality
        is a whole unit's worth of milliseconds, so it becomes a range.
        """
        if not isinstance(value, int) or isinstance(value, bool):
            raise Unsupported(f"policy compares an integer from a duration conversion against "
                              f"{value!r}, which is not an integer")
        # Clamped to the day, which is every value a time of day takes: `toDays() >= 25` is never
        # true, and should be checked as never true rather than refused as too big for TLC.
        lo, hi = (min(max(v * unit, 0), DAY_MS) for v in (value, value + 1))

        def cmp(c: str, v: int) -> dict:
            return {"op": "cmp", "field": SYSTEM_NOW, "cmp": c, "value": v}

        if op == ">=":
            return cmp(">=", lo)
        if op == ">":
            return cmp(">=", hi)
        if op == "<":
            return cmp("<", lo)
        if op == "<=":
            return cmp("<", hi)
        within = {"op": "and", "args": [cmp(">=", lo), cmp("<", hi)]}
        return within if op == "==" else {"op": "not", "args": [within]}

    def ip_method_ahead(self) -> bool:
        """Does an ipaddr method follow the context field at the cursor?

        `context . input . src . isInRange` is seven fixed tokens, so this is a peek rather than a
        scan -- `context_field` accepts exactly that shape and nothing longer.
        """
        # `context.system.now.toTime()` is the same length and shape, so the `input` check keeps
        # the system clock out of the ipaddr path -- where it would be reported as a bad CIDR.
        return (self.peek(2) == "input" and self.peek(5) == "."
                and self.peek(6) in ("isInRange",) + IP_METHODS_UNARY)

    def ip_test(self) -> dict:
        """`context.input.FIELD.isInRange(ip("CIDR"))`."""
        field = self.context_field()
        self.expect(".")
        method = self.take()

        if method in IP_METHODS_UNARY:
            raise Unsupported(
                f"policy calls `.{method}()`, which is not modelled -- only `isInRange` is",
                "uses an ipaddr method other than isInRange")
        if method != "isInRange":
            raise Unsupported(f"policy calls `.{method}()` on a context field, which is not "
                              f"modelled")

        self.expect("(")
        if self.take() != "ip":
            raise Unsupported("`isInRange` takes an `ip(\"...\")` literal, and this is not one")
        self.expect("(")
        tok = self.take()
        if not tok.startswith('"'):
            raise Unsupported(f"ip() argument {tok!r} is not a string literal -- Cedar requires "
                              f"one, and a computed address cannot be checked here either")
        self.expect(")")
        self.expect(")")

        net, prefix = parse_cidr(tok[1:-1])
        return {"op": "inrange", "field": field, "net": net, "prefix": prefix}

    def context_field(self) -> str:
        self.expect("context")
        self.expect(".")

        # `context.system.now.toTime()` -- the decision's wall-clock time of day. The only part of
        # `context.system` modelled: `now` compared as a datetime would need calendar arithmetic,
        # and a policy that reads one is told so rather than approximated.
        if self.peek() == "system":
            self.take()
            self.expect(".")
            if (what := self.take()) != "now":
                raise Unsupported(f"policy reads context.system.{what}, which is not modelled -- "
                                  f"only `now`")
            if self.peek() != ".":
                raise Unsupported(
                    "policy compares context.system.now as a datetime, which is not modelled. "
                    "Only `.toTime()` is -- the time of day, which is what a business-hours rule "
                    "compares. A datetime comparison would need calendar arithmetic",
                    "compares the wall clock as a datetime")
            self.expect(".")
            if (method := self.take()) != "toTime":
                raise Unsupported(
                    f"policy calls context.system.now.{method}(), which is not modelled. Only "
                    f"`.toTime()` is -- the time of day, which is what a business-hours rule "
                    f"compares. A datetime comparison would need calendar arithmetic")
            self.expect("(")
            self.expect(")")
            return SYSTEM_NOW

        self.expect("input")
        self.expect(".")
        return self.own_field(self.take())

    def own_field(self, name: str) -> str:
        """A field the policy names itself, refused if it collides with the synthetic clock.

        `context.system.now.toTime()` becomes a request field called `systemNowTime`, because a
        field name has to be a TLA+ identifier and so cannot be `system.now`. That puts it in the
        same namespace as the policy's own fields. A policy reading an input field of that name
        alongside the clock would have the two conflated, and every verdict about one would
        silently be a verdict about the other -- so it is refused instead.
        """
        if name == SYSTEM_NOW:
            raise Unsupported(
                f"policy reads an input field called {SYSTEM_NOW!r}, which is the name this model "
                f"gives context.system.now.toTime(). Rename the field: keeping both would make "
                f"one indistinguishable from the other")
        return name

    def comparison_op(self) -> str:
        op = self.take()
        if op == "like":
            # Reachable only where the left side is not a context field -- a bound variable, say.
            # `context.input.x like "..."` is handled in `comparison` and never arrives here.
            raise Unsupported(
                "policy uses `like` on something other than a context field, which is not modelled",
                "uses a Cedar operator we do not model")
        if op in ("has", "in", "is"):
            raise Unsupported(f"policy uses Cedar's `{op}` operator, which is not modelled",
                              "uses a Cedar operator we do not model")
        if op not in ("==", "!=", ">=", "<=", ">", "<"):
            raise Unsupported(f"comparison operator {op!r}")
        return op

    def literal(self):
        """A scalar written where a comparison expects one."""
        neg = self.accept("-")
        tok = self.take()
        if tok.startswith('"'):
            return tok[1:-1]
        if tok in ("true", "false"):
            return tok == "true"
        if re.fullmatch(r"\d+", tok):
            return bounded(-int(tok) if neg else int(tok), "a value the policy compares against")
        if tok == "decimal":
            self.expect("(")
            text = self.take()
            self.expect(")")
            return parse_decimal(text[1:-1])
        if tok == "duration":
            self.expect("(")
            text = self.take()
            self.expect(")")
            if not text.startswith('"'):
                raise Unsupported(f"duration() argument {tok!r} is not a string literal")
            return parse_duration(text[1:-1])
        raise Unsupported(f"comparison operand {tok!r} is not a literal")

    def duration(self, tok: str) -> int:
        m = re.fullmatch(r"(\d+)([smhd])", tok)
        if not m:
            raise Unsupported(f"duration {tok!r}")
        seconds = int(m.group(1)) * UNITS[m.group(2)]

        # The schema's ceiling on history. Checked HERE, where a window is read, so one nested
        # inside an aggregation body is caught as surely as a top-level `formerly`.
        #
        # `None` means no cap, and exists for ONE caller: the differential, which is an oracle for
        # what the engine EVALUATES. The cap is a validation rule, and the engine corpus contains
        # two cases the validator rejects -- deliberately, to stress window arithmetic over a huge
        # gap. Refusing them there would lose evidence about evaluation to enforce a rule about
        # deployment.
        if self.max_window is not None and seconds > self.max_window:
            raise Unsupported(
                f"window `within {tok}` looks back further than the event schema allows "
                f"({fmt_window(self.max_window)}); the validator rejects it, so the policy could "
                f"not be deployed as written",
                "window exceeds the schema's max_window")
        return seconds

    def pred(self) -> dict:
        self.take()                      # namespace
        self.expect("::")
        self.expect("Action")
        self.expect("::")
        action = self.take()
        if not action.startswith('"'):
            raise Unsupported(f"action name {action!r}")
        self.expect("::")
        kind = self.take()
        self.expect("{")
        binds = []
        if self.peek() != "}":
            binds.append(self.bind())
            while self.accept(","):
                binds.append(self.bind())
        self.expect("}")

        # The INJECTION operator -- `?s{ input.status: "approved" }` in a macro body, which after
        # splicing leaves `PRED{ caller binds }{ injected binds }`. It forces a field onto whatever
        # predicate the caller passed, even one the caller never mentions; corpus case
        # 1116_injection_onto_deep_path uses it to impose a same-session correlation.
        #
        # Merging is just concatenation. Every bind has to match the same event, so if an injection
        # names a field the caller already bound to a different value, the conjunction is
        # unsatisfiable -- which is the right answer and needs no special case.
        while self.peek() == "{":
            self.take()
            if self.peek() != "}":
                binds.append(self.bind())
                while self.accept(","):
                    binds.append(self.bind())
            self.expect("}")

        return {"action": action[1:-1], "kind": kind, "binds": binds}

    def bind(self) -> dict:
        lhs = self.take()

        if lhs in ("callerPrincipal", "callerResource"):
            self.expect(":")
            rhs = self.take()
            # A wildcard on a scope field matches any caller -- and CANNOT bypass a universal pin,
            # which partitions the candidate events before any bind is consulted. Corpus case
            # 1119 is named for exactly that: `pin_not_bypassed_by_wildcard`.
            if rhs in ("_", "*"):
                return {"side": "scope", "field": lhs, "kind": "any", "name": "", "value": ""}
            # A bare name binds the event's caller to a variable, so two predicates can correlate
            # on "the same principal" without naming which -- `exists (pr: Drupe::OAuthUser)`.
            if rhs not in ("principal", "resource"):
                if re.fullmatch(r"[A-Za-z_]\w*", rhs):
                    return {"side": "scope", "field": lhs, "kind": "var", "name": rhs, "value": ""}
                raise Unsupported(f"scope bind value {rhs!r}")
            return {"side": "scope", "field": lhs, "kind": "scope", "name": rhs, "value": ""}

        # The one nested reserved leaf the corpus writes directly. Deeper paths under
        # `__drupe` are a separate feature and stay refused.
        if lhs == "__drupe":
            self.expect(".")
            leaf = self.take()
            if leaf != "session_id":
                raise Unsupported(f"bind target __drupe.{leaf}")
            self.expect(":")
            tok = self.take()
            if not tok.startswith('"'):
                raise Unsupported(f"__drupe.session_id bound to {tok!r}, not a literal")
            return {"side": "scope", "field": "__drupe.session_id", "kind": "lit",
                    "name": "", "value": tok[1:-1]}

        if lhs not in ("input", "output"):
            raise Unsupported(f"bind target {lhs!r}")
        self.expect(".")
        field = self.take()
        self.expect(":")

        nxt = self.peek()
        # `_` and `*` are both "matches anything, binds nothing". The grammar gives `*` its own
        # rule and `_` falls out of `ident` as a variable no one else names; the two coincide, and
        # the corpus writes `_` while the examples write `*`.
        if nxt in ("_", "*"):
            self.take()
            return {"side": lhs, "field": field, "kind": "any", "name": "", "value": ""}
        if nxt == "context":
            self.take()
            self.expect(".")
            self.expect("input")
            self.expect(".")
            return {"side": lhs, "field": field, "kind": "ctx", "name": self.take(), "value": ""}
        if nxt in ("true", "false"):
            return {"side": lhs, "field": field, "kind": "lit", "name": "",
                    "value": self.take() == "true"}
        if nxt and nxt.startswith('"'):
            return {"side": lhs, "field": field, "kind": "lit", "name": "",
                    "value": self.take()[1:-1]}

        # An integer literal: `input.level: 3`.
        neg = self.accept("-")
        if self.peek() and re.fullmatch(r"\d+", self.peek()):
            n = int(self.take())
            return {"side": lhs, "field": field, "kind": "lit", "name": "",
                    "value": bounded(-n if neg else n, f"the value bound to {lhs}.{field}")}
        if neg:
            raise Unsupported(f"bind value '-{self.peek()}'")

        # `decimal("0.50")` -- Cedar's decimal. Carried scaled so 0.5 and 0.50 are one number,
        # which is what the corpus pairs a policy literal against in a trace.
        if nxt == "decimal":
            self.take()
            self.expect("(")
            tok = self.take()
            if not tok.startswith('"'):
                raise Unsupported(f"decimal argument {tok!r} is not a literal")
            self.expect(")")
            return {"side": lhs, "field": field, "kind": "lit", "name": "",
                    "value": parse_decimal(tok[1:-1])}

        # An entity reference -- `Drupe::Grant_Input_role::"reader"`. Compared as its written
        # form, which is how the trace carries it too.
        if nxt and re.fullmatch(r"[A-Za-z_]\w*", nxt) and self.peek(1) == "::":
            parts = [self.take()]
            while self.accept("::"):
                parts.append(self.take())
            text = "::".join(parts[:-1]) + "::" + parts[-1]
            return {"side": lhs, "field": field, "kind": "lit", "name": "", "value": text}

        # A bare identifier is a variable bound by an enclosing `count`/`sum`.
        if nxt and re.fullmatch(r"[A-Za-z_]\w*", nxt):
            return {"side": lhs, "field": field, "kind": "var", "name": self.take(), "value": ""}
        raise Unsupported(f"bind value {nxt!r}")


# `def temporal once(?w, ?s) {` -- the header only; the body is brace-matched from the `{`,
# because a macro body contains predicates with braces of their own and a regex cannot count them.
DEF_HEAD = re.compile(r"\bdef\s+(cedar|temporal)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{")


# THE LARGEST INTEGER LITERAL TLC WILL ACCEPT, measured rather than assumed: 2147483646 checks
# cleanly and 2147483647 fails, so TLC holds integers in a Java int and reserves
# `Integer.MAX_VALUE`. TLA+ itself has unbounded integers -- this is the model CHECKER's limit,
# not the language's, which is why the number is odd rather than a power of two.
TLC_MAX_INT = 2147483646


def bounded(n: int, what: str) -> int:
    """An integer literal the checker can actually hold, or a refusal naming why it cannot.

    WITHOUT THIS THE FAILURE ARRIVES FROM INSIDE TLC -- `Error: TLC can't handle a number this
    big.` followed by the bare number, from a run that names neither the policy nor the field it
    came from, at a point where the reader has no reason to suspect the literal. A Cedar `Long`
    runs to 2^63-1, so a policy comparing against one is perfectly valid and simply outside what a
    bounded model checker can represent. That is exactly the case the house rule covers: refuse,
    and say which construct is responsible.
    """
    if not -TLC_MAX_INT <= n <= TLC_MAX_INT:
        raise Unsupported(
            f"{what} is {n}, which TLC cannot represent. It holds integers in a Java int and "
            f"reserves Integer.MAX_VALUE, so a literal has to fit in +/-{TLC_MAX_INT}. Cedar's "
            f"Long goes to 2^63-1, so the policy is valid and this is the checker's limit rather "
            f"than the language's. Scaling the units -- cents to dollars, bytes to megabytes -- "
            f"makes the same comparison fit")
    return n

MAX_EXPANSION_DEPTH = 8


def collect_macros(text: str) -> tuple[dict, str]:
    """Pull every `def` out of the text, returning the macros and what is left.

    The remainder is what the policy scanner then reads, so a definition can never be mistaken for
    a policy or leave a stray `;` behind.
    """
    macros, out, i = {}, [], 0
    while (m := DEF_HEAD.search(text, i)) is not None:
        out.append(text[i:m.start()])

        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += (text[j] == "{") - (text[j] == "}")
            j += 1
        if depth:
            raise Unsupported(f"macro {m.group(2)}() has an unterminated body")

        params = [q.strip().lstrip("?") for q in m.group(3).split(",") if q.strip()]
        macros[m.group(2)] = {"kind": m.group(1), "params": params,
                              "body": tokenize(text[m.end():j - 1])}
        i = j + 1 if text[j:j + 1] == ";" else j    # the `;` closing the declaration
    out.append(text[i:])
    return macros, "".join(out)


def split_args(tokens: list[str], open_at: int) -> tuple[list[list[str]], int]:
    """The comma-separated arguments of a call whose `(` is at `open_at`, and the index past `)`.

    Nesting counts every bracket kind, because an argument is routinely a whole predicate --
    `once(1h, Drupe::Action::"Read"::response{ input.user: context.input.user })` -- whose braces
    contain a comma that is not an argument separator.
    """
    args, cur, depth, j = [], [], 0, open_at
    while j < len(tokens):
        tok = tokens[j]
        if tok in ("(", "{", "["):
            depth += 1
            if depth > 1:
                cur.append(tok)
        elif tok in (")", "}", "]"):
            depth -= 1
            if depth == 0:
                if cur or args:
                    args.append(cur)
                return args, j + 1
            cur.append(tok)
        elif tok == "," and depth == 1:
            args.append(cur)
            cur = []
        else:
            cur.append(tok)
        j += 1
    raise Unsupported("unbalanced brackets in a macro call")


def expand_macros(tokens: list[str], macros: dict, counter: list[int],
                  depth: int = 0) -> list[str]:
    """Splice every macro call in `tokens`, recursively.

    `?p` takes the call-site tokens literally and `$t` becomes a fresh binder per expansion, both
    as the reference grammar specifies. The depth limit stands in for a cycle check:
    `def a() { b() }; def b() { a() };` would otherwise not terminate, and refusing at a bound
    keeps that from being a hang.
    """
    if depth > MAX_EXPANSION_DEPTH:
        raise Unsupported(f"macro expansion nested deeper than {MAX_EXPANSION_DEPTH} "
                          f"-- the definitions may be mutually recursive")

    out, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok not in macros or tokens[i + 1:i + 2] != ["("]:
            out.append(tok)
            i += 1
            continue

        macro = macros[tok]
        args, after = split_args(tokens, i + 1)
        if len(args) != len(macro["params"]):
            raise Unsupported(f"macro {tok}() takes {len(macro['params'])} argument(s) "
                              f"but is called with {len(args)}")

        bound = {f"?{q}": expand_macros(a, macros, counter, depth + 1)
                 for q, a in zip(macro["params"], args)}

        # One gensym per EXPANSION, not per definition: two calls to the same macro in one policy
        # must not share a binder, or the second would capture the first's timepoints.
        fresh: dict[str, str] = {}
        body: list[str] = []
        for t in macro["body"]:
            if t in bound:
                body.extend(bound[t])
            elif t.startswith("$"):
                if t not in fresh:
                    counter[0] += 1
                    fresh[t] = f"__{t[1:]}_{counter[0]}"
                body.append(fresh[t])
            else:
                body.append(t)

        out.extend(expand_macros(body, macros, counter, depth + 1))
        i = after
    return out


def fmt_window(seconds: int) -> str:
    """Seconds back in the units a policy would write them.

    Days only from two upward: the default cap is 86400 seconds and everyone writes that `24h`,
    which is also how the guide spells it.
    """
    if seconds % 86400 == 0 and seconds >= 2 * 86400:
        return f"{seconds // 86400}d"
    for unit, size in (("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def parse_policies(text: str, macros_text: str = "",
                   max_window: int | None = DEFAULT_MAX_WINDOW) -> list[dict]:
    """Every `permit`/`forbid` in the file, as [effect, action, cond].

    `macros_text` is a separate `macros.dw`, whose definitions are in scope for `text`. Inline
    `def`s in `text` are collected the same way, so the two spellings are one mechanism.
    """
    text = re.sub(r"//[^\n]*", "", text)
    macros_text = re.sub(r"//[^\n]*", "", macros_text)

    shared, leftover = collect_macros(macros_text)
    local, text = collect_macros(text)
    if leftover.strip():
        raise Unsupported("the macros file holds more than definitions")
    macros = {**shared, **local}

    policies = []

    for m in re.finditer(r"(permit|forbid)\s*\((.*?)\)\s*(.*?);", text, re.S):
        effect, scope, body = m.group(1), " ".join(m.group(2).split()), " ".join(m.group(3).split())

        sm = re.fullmatch(r'principal,\s*action == \w+::Action::"([^"]+)",\s*resource', scope)
        im = re.fullmatch(r"principal,\s*action in \[([^\]]*)\],\s*resource", scope)
        if sm:
            actions = [sm.group(1)]
        elif im:
            # `action in [Drupe::Action::"Read", Drupe::Action::"Write"]` -- the policy applies to
            # any of them. A set, so this is not a third shape.
            actions = re.findall(r'\w+::Action::"([^"]+)"', im.group(1))
            if not actions:
                raise Unsupported(f"action set {im.group(1)!r} names no actions")
        elif re.fullmatch(r"principal,\s*action,\s*resource", scope):
            # A bare `action` constrains nothing: the policy applies to EVERY action. The empty
            # SET says that, where an empty string was a sentinel a real action could collide with.
            actions = []
        else:
            # A constrained `principal` or `resource` changes what the policy applies to, and
            # scope entities beyond the pin correlation are not modelled.
            raise Unsupported(f"scope {scope!r}")

        if not body:
            policies.append({"effect": effect, "actions": actions,
                             "cond": {"op": "true", "args": []}})
            continue

        p = Parser(expand_macros(tokenize(body), macros, [0]), max_window)
        cond = p.body()
        if p.peek() is not None:
            raise Unsupported(f"trailing tokens from {p.peek()!r}")

        policies.append({"effect": effect, "actions": actions, "cond": cond})

    if not policies:
        raise Unsupported("no policies parsed")
    return policies
