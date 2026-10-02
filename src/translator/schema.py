"""Reading an `event.dwschema`, for the one thing in it that changes what a policy MEANS: pins.

A pin declares that a field of every event is implicitly forced to equal something about the
decision. The policy never writes it, cannot see it, and cannot bypass it:

    decision event <A>::request {
        ...inputs(A),
        pin callerPrincipal: principalType(A) = principal,
        ...
    }

That is the finding this module exists for. **A policy's meaning is not determined by its own
text** — read the `.dw` and ignore the schema and you get a different answer than the engine does.
It is also what caught our translator the first time the corpus ran.

UNIVERSAL VERSUS PARTIAL, which is the subtle half. A pin declared on EVERY event kind is
universal and switches the leaf to key-local semantics: the trace is partitioned by the pinned key
and temporal operators see only your own partition. A pin declared on some kinds but not others is
partial, earns no isolation, and stays global — the corpus's own words: "the engine must not grant
isolation the schema did not earn."

The difference is invisible to `formerly`, `count` and `sum`, which are existential — restricting
the candidates is the same as adding a conjunct. It is visible to `previous`, which means *the most
recent match*: globally a foreign event can BE the most recent one and fail the predicate, where
partitioned it is skipped entirely. `1155_relativize_previous_ignores_foreign` and
`1164_partial_pin_stays_global` are the same policy and the same trace with opposite verdicts, and
the only difference between them is whether the pin covers both kinds.

THE MODELLED SUBSET is universal and partial pins on the two SCOPE fields, `callerPrincipal` and
`callerResource`. Everything else here is refused rather than guessed at:

    - nested pins (`__drupe: { pin session_id: ... }`), which pin a path rather than a field
    - pins on a context field (`pin tenant_id: String = context.tenant_id`)
    - schemas with custom event kinds (`attempt`/`outcome` rather than request/response)
    - schemas with no pin at all, which are in the corpus for other features entirely --
      renamed reserved fields, deep paths, injected slots
"""

from __future__ import annotations

import re

from .parse import DEFAULT_MAX_WINDOW, DEFAULT_SCOPE_FIELDS, UNITS, Unsupported

# `pin <field>: <type> = <source>` at the top level of an event block.
PIN = re.compile(r"^\s*pin\s+([A-Za-z_]\w*)\s*:\s*[^=]+=\s*([A-Za-z_][\w.]*)\s*,?\s*$", re.M)

# `__drupe: { pin session_id: String = context.__drupe.session_id }` -- a pin on a leaf inside a
# reserved group. Captured as (group, leaf, source) and treated as the dotted path it names.
NESTED_PIN = re.compile(
    r"([A-Za-z_]\w*)\s*:\s*\{\s*pin\s+([A-Za-z_]\w*)\s*:\s*[^=]+=\s*([A-Za-z_][\w.]*)\s*\}", re.S)

EVENT = re.compile(r"^\s*(decision\s+)?event\s+<A>::([A-Za-z_]\w*)\s*\{", re.M)

# `max_window = 30d` -- the ceiling on how far back any `within` may look. First in the file, at
# most once; absent, the language default of 24h applies.
MAX_WINDOW = re.compile(r"^\s*max_window\s*=\s*(\d+)([smhd])\s*$", re.M)

CONVENTIONAL = {"request", "response", "error"}

# The fields the default AgentCore event schema declares. A schema carrying only these, pinned or
# not, tells the model nothing it does not already assume; one carrying anything else is declaring
# a feature -- an injected slot, a renamed slot, a nested or deep group -- and every such feature
# changes what a policy means.
#
# Read off the corpus rather than off the documentation: all nine schema-bearing cases with no pin
# declare a field outside this set, and that is what each of them is in the corpus to test.
#
# The two SCOPE fields are not in it by name: a schema may call them anything (below).
CONVENTIONAL_FIELDS = {"...inputs", "...outputs", "requestId", "sessionId"}

# A top-level entry in an event block: `name: type`, `pin name: type = source`, or `...inputs(A)`.
FIELD = re.compile(r"^\s*(?:pin\s+)?(\.\.\.[A-Za-z_]\w*|[A-Za-z_]\w*)\s*[:(]", re.M)

# The two SCOPE fields. These partition on something the event carries in its `scope(...)`
# envelope rather than in its payload, which is why they stay special everywhere below. These are
# the names the model uses for them INTERNALLY, which are Dogwood's default names.
SCOPE_PINS = {"callerPrincipal": "principal", "callerResource": "resource"}

# A schema says which fields ARE the scope fields by their type, not their name -- Dogwood's own
# rule (guide 03-event-schema.md, "How request references resolve"): `actor: principalType(A)` is
# the principal however it is spelled. AgentCore spells them `eventPrincipal` / `eventResource`.
SCOPE_TYPED = re.compile(
    r"^\s*(?:pin\s+)?([A-Za-z_]\w*)\s*:\s*(principalType|resourceType)\s*\(\s*A\s*\)", re.M)
SCOPE_SELECTORS = {"principalType": "callerPrincipal", "resourceType": "callerResource"}


def key_for(field: str) -> str:
    """The partition key a pinned field maps to.

    Scope fields have their own names; anything else keys on its own last path segment, which is
    also the name its value is stored under on each event. `__drupe.session_id` and a top-level
    `session_id` would collide, and neither the corpus nor the grammar puts both in one schema.
    """
    return SCOPE_PINS.get(field) or field.rsplit(".", 1)[-1]


def _block(text: str, start: int) -> str:
    """The braced block beginning at `start` (just past its opening brace)."""
    depth, j = 1, start
    while j < len(text) and depth:
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
        j += 1
    return text[start:j]


def parse_schema(text: str) -> dict:
    """`{"keys": [...], "max_window": secs, "partial": {kind: [bind, ...]}}` for a schema.

    `keys` are the partition keys a universal pin establishes -- empty when there is none, which
    is the same as having no schema at all. `partial` gives the binds to inject per event kind.
    """
    text = re.sub(r"//[^\n]*", "", text)

    cap = MAX_WINDOW.search(text)
    if cap:
        seconds = int(cap.group(1)) * UNITS[cap.group(2)]
        if seconds == 0:
            raise Unsupported("max_window = 0 would forbid every `within` clause; the schema "
                              "should omit the directive instead")
        max_window = seconds
    else:
        max_window = DEFAULT_MAX_WINDOW

    kinds, pins, blocks, pinned, scope_by_kind = [], {}, {}, {}, {}
    for m in EVENT.finditer(text):
        kind = m.group(2)
        kinds.append(kind)
        block = _block(text, m.end())
        blocks[kind] = block
        # Surface name -> internal name, for the fields typed as the scope entities.
        scope_by_kind[kind] = {name: SCOPE_SELECTORS[sel] for name, sel in SCOPE_TYPED.findall(block)}
        declared = {scope_by_kind[kind].get(f, f): src for f, src in PIN.findall(block)}
        # The names a pin is attached to, whatever their shape. A field outside the default set
        # is the modelled feature when it carries one, and an unmodelled one when it does not.
        names = set(declared)
        # `__drupe: { pin session_id: String = context.__drupe.session_id }` -- a pin on a leaf
        # inside a reserved group, which reads as the dotted path it names.
        for group, leaf, source in NESTED_PIN.findall(block):
            declared[f"{group}.{leaf}"] = source
            names.add(group)
        pins[kind] = declared
        pinned[kind] = names

    if not kinds:
        raise Unsupported("event schema declares no event kinds")

    unknown = set(kinds) - CONVENTIONAL
    if unknown:
        raise Unsupported(f"schema declares custom event kinds: {', '.join(sorted(unknown))}")

    # One spelling of the scope fields for the whole schema. A policy names a field once and means
    # it on every kind, so a schema calling the principal `actor` on one kind and `caller` on
    # another would make the same bind mean different things depending on the event.
    spellings = {tuple(sorted(s.items())) for s in scope_by_kind.values()}
    if len(spellings) > 1:
        raise Unsupported("event schema names its scope fields differently on different kinds",
                          "schema declares a field beyond the default shape")
    scope_fields = dict(spellings.pop()) if spellings else {}

    # What the schema declares beyond the default shape. A pin on a conventional field is the
    # modelled feature; anything else is a different one, and is named rather than lumped in.
    for kind, block in blocks.items():
        pinned_surface = pinned[kind] | set(scope_fields)
        extra = sorted({f for f in FIELD.findall(block)
                        if f not in CONVENTIONAL_FIELDS and f not in pinned_surface})
        if extra:
            raise Unsupported(
                f"event schema declares {', '.join(extra)} on <A>::{kind}, which is an injected, "
                f"renamed or nested slot rather than a pin -- a separate feature, not modelled",
                "schema declares a field beyond the default shape")

    declared = set().union(*pins.values()) if pins else set()



    for kind, declared_here in pins.items():
        for field, source in declared_here.items():
            if field in SCOPE_PINS:
                # `pin callerPrincipal: ... = principal` -- rooted at the request scope.
                if source != SCOPE_PINS[field]:
                    raise Unsupported(f"pin {field} = {source}, not its own scope entity")
            # Otherwise rooted at the request context, and only the SYMMETRIC form is modelled:
            # the context path it reads must be the field path it constrains. An asymmetric pin
            # relates two different things and is not this.
            elif source != f"context.{field}":
                raise Unsupported(f"pin {field} = {source} is asymmetric, not context.{field}")

    universal = [f for f in sorted(declared) if all(f in pins[k] for k in kinds)]
    partial = sorted(declared - set(universal))

    return {
        # Which names a policy may use for the scope fields under this schema, and the internal
        # name each stands for. Under AgentCore's, `eventResource: resource` is a bind on the
        # resource; `callerResource` is not a declared field at all.
        "scope_fields": scope_fields,
        "keys": [key_for(f) for f in universal],
        # The ceiling on how far back any `within` may look. 24h unless the schema says otherwise,
        # and a policy exceeding it is a validation error -- so it could not be deployed as written.
        "max_window": max_window,
        # Where to read each non-scope key's value out of an event, so the trace parser can pull
        # exactly the fields that matter and nothing else.
        "paths": {key_for(f): f for f in universal if f not in SCOPE_PINS},
        # A partial pin earns no partition, so it acts as an ordinary conjunct on the kinds that
        # declare it -- and on those only.
        "partial": {kind: [_bind(f) for f in sorted(partial) if f in pins[kind]]
                    for kind in kinds},
    }


def _bind(field: str) -> dict:
    """The bind a PARTIAL pin injects -- the same record the parser builds for a written one."""
    if field not in SCOPE_PINS:
        raise Unsupported(f"partial pin on {field}, which has no written form to inject")
    return {"side": "scope", "field": field, "kind": "scope",
            "name": SCOPE_PINS[field], "value": ""}


def apply_pins(policies: list[dict], schema: dict) -> None:
    """Inject each partial pin's bind into the predicates of the kind that declares it.

    In place, and only for PARTIAL pins. A universal pin needs no conjunct: partitioning already
    restricts every candidate to events that agree on the key, so writing it in as well would be
    the same condition twice.
    """
    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if pred := node.get("pred"):
            for b in schema["partial"].get(pred.get("kind"), []):
                if not any(x["field"] == b["field"] and x["side"] == "scope"
                           for x in pred["binds"]):
                    pred["binds"].append(b)
        for key in ("term", "atom", "left", "cond", "agg"):
            walk(node.get(key))
        for child in node.get("args", []) or []:
            walk(child)

    for p in policies:
        walk(p["cond"])
