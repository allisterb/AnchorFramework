-------------------------- MODULE DogwoodSemantics --------------------------
(***************************************************************************)
(* Our reading of Dogwood's temporal operators, written so it can be held  *)
(* against the reference implementation's own regression corpus.           *)
(*                                                                         *)
(* TemporalPolicy.tla asks what a policy set could do over ALL sessions.   *)
(* This module asks a narrower and more checkable question: on THESE       *)
(* recorded sessions, does our evaluator return what Dogwood returned? The *)
(* corpus supplies both halves -- policies plus traces, and the verdicts   *)
(* their engine produced -- so a misreading shows up as a disagreement     *)
(* naming the exact case and decision point.                              *)
(*                                                                         *)
(* Every case is checked in one run: per-case JVM startup dominated        *)
(* everything else when each paid for its own.                             *)
(*                                                                         *)
(* WHAT THE CORPUS PINNED DOWN, none of it obvious from the prose:         *)
(*                                                                         *)
(*   - `@N` in a trace is SECONDS, and the window is inclusive. Case 0127  *)
(*     fixes it: under `within 10s` a read 12s after a login is denied and *)
(*     one 8s after is allowed.                                            *)
(*   - The decision sees the trace UP TO AND INCLUDING its own event,      *)
(*     which is what AgentCore documents for self-referential conditions.  *)
(*   - Deny by default: where no permit matches, the verdict is false.     *)
(*   - `count` counts DISTINCT ASSIGNMENTS to the bound variables, not     *)
(*     matching events. Case 0254 is the Rosetta stone: four identical     *)
(*     transfers, `count for (t: Timepoint)` over a `tp(t)`-bound          *)
(*     predicate, forbidden at `n >= 3` -- and the verdicts flip on the    *)
(*     third, which only works if the current request counts itself.       *)
(*                                                                         *)
(* THE SEMANTICS OF `since`, `previous` AND THE AGGREGATIONS ARE INFERRED, *)
(* not documented. They are written as standard past-time MFOTL and then   *)
(* checked against the corpus, which is the only reason to believe them.   *)
(***************************************************************************)
\* Integers rather than Naturals: SumOver guards on `\in Int`, because a bound variable's
\* domain is every scalar the trace contains and only some of them are numbers.
EXTENDS Integers, Sequences, FiniteSets, TLC

(***************************************************************************)
(* SUPPLIED BY THE GENERATED MODULE                                        *)
(*                                                                         *)
(*   Cases   Seq of [name, trace, policies, oracle, values]                *)
(*     trace     Seq of [time, action, kind, input, output,                *)
(*                       principal, resource, isDecision]                  *)
(*     policies  Seq of [effect, action, cond]                             *)
(*     oracle    function from decision index to BOOLEAN                   *)
(*     values    every scalar appearing in the trace -- the domain a bound *)
(*               variable of non-Timepoint type ranges over                *)
(***************************************************************************)
CONSTANT Cases

(***************************************************************************)
(* BINDS -- the first-order half of the logic. A bind joins a field of a   *)
(* past event to the request's input, to a scope entity, to a literal, to  *)
(* a bound variable, or to nothing at all (`_`).                           *)
(*                                                                         *)
(* Presence is checked structurally, through DOMAIN, rather than against a *)
(* sentinel value. A sentinel would have to be comparable with every field *)
(* type, and `output.result: true` puts a BOOLEAN on one side of that.     *)
(***************************************************************************)
(***************************************************************************)
(* Equality that survives comparing values of different kinds.             *)
(*                                                                         *)
(* A bound variable ranges over every scalar the trace contains, so a      *)
(* Timepoint binder gets offered strings and a String binder gets offered  *)
(* integers. TLC refuses `=` across kinds outright, and refuses `\in Int`   *)
(* for a non-integer as well, so neither the comparison nor a type test in *)
(* front of it is available.                                               *)
(*                                                                         *)
(* So every scalar is TAGGED at generation time -- [k |-> "s"|"n"|"b"|"t", *)
(* v |-> ...] -- and comparison checks the kind first. `/\` short-circuits, *)
(* so the values are only compared once the kinds agree.                   *)
(***************************************************************************)
SameVal(x, y) == x.k = y.k /\ x.v = y.v

\* A trace index, in the same tagged shape as a field value.
TP(i) == [k |-> "t", v |-> i]

BindHolds(b, ev, dec, asg) ==
    LET rec == CASE b.side = "input"  -> ev.input
                 [] b.side = "output" -> ev.output
                 [] OTHER             -> [caller |-> ev.principal, callerRes |-> ev.resource,
                                              sess |-> ev.session]
        fld == CASE b.side \in {"input", "output"} -> b.field
                 [] b.field = "callerPrincipal"    -> "caller"
                 [] b.field = "callerResource"     -> "callerRes"
                 \* `__drupe.session_id`, written by the author rather than injected.
                 [] OTHER                          -> "sess"
    IN /\ fld \in DOMAIN rec
       /\ CASE b.kind = "any"   -> TRUE
            [] b.kind = "lit"   -> SameVal(rec[fld], b.value)
            [] b.kind = "var"   -> /\ b.name \in DOMAIN asg
                                   /\ SameVal(rec[fld], asg[b.name])
            [] b.kind = "scope" -> SameVal(rec[fld], IF b.name = "principal" THEN dec.principal
                                                                            ELSE dec.resource)
            [] OTHER            -> /\ b.name \in DOMAIN dec.input
                                   /\ SameVal(rec[fld], dec.input[b.name])

Matches(pred, ev, dec, asg) ==
    /\ ev.action = pred.action
    /\ ev.kind = pred.kind
    /\ \A j \in DOMAIN pred.binds : BindHolds(pred.binds[j], ev, dec, asg)

(***************************************************************************)
(* ATOMS are evaluated AT A CANDIDATE EVENT, not at the decision point.    *)
(*                                                                         *)
(* `formerly within 1h (P && tp(t))` searches for an event matching P and  *)
(* binds `t` to THAT event's index. So the group's meaning depends on      *)
(* which candidate is under consideration, which is why this is a separate *)
(* evaluation indexed by `i` rather than part of CondHolds.                *)
(***************************************************************************)
(***************************************************************************)
(* A comparison on the DECISION event's own context, e.g.                  *)
(*                                                                         *)
(*     formerly within 1h (Login::request{..} && context.input.amount > 100) *)
(*                                                                         *)
(* Note what it does NOT read: the candidate event. `i` is not mentioned    *)
(* below, so a comparison evaluates identically at every candidate index -- *)
(* it filters the REQUEST, not the history, and sits inside the group only  *)
(* because that is where the author wrote it.                              *)
(*                                                                         *)
(* Kind is compared before value, as everywhere else here, because TLC      *)
(* refuses `=` across a string and an integer rather than returning FALSE.  *)
(* A field the decision event does not carry makes the comparison FALSE.    *)
(***************************************************************************)
(***************************************************************************)
(* `context.input.amount > context.input.limit` -- two fields of the SAME  *)
(* request compared against each other rather than against a literal.      *)
(* Reads `dec` only, like the literal form, so it filters the request.     *)
(***************************************************************************)
Cmp2Holds(a, dec) ==
    /\ a.field \in DOMAIN dec.input
    /\ a.other \in DOMAIN dec.input
    /\ LET x == dec.input[a.field]
           y == dec.input[a.other]
       IN /\ x.k = y.k
          /\ CASE a.cmp = "==" -> x.v = y.v
               [] a.cmp = "!=" -> x.v # y.v
               \* Integers only -- decimals are part of what that excludes. See CmpHolds for
               \* why; a pair of any other kind compares FALSE here rather than crashing.
               [] a.cmp = ">"  -> x.k = "n" /\ x.v > y.v
               [] a.cmp = "<"  -> x.k = "n" /\ x.v < y.v
               [] a.cmp = ">=" -> x.k = "n" /\ x.v >= y.v
               [] a.cmp = "<=" -> x.k = "n" /\ x.v <= y.v
               [] OTHER        -> FALSE

(***************************************************************************)
(* `a > 0` -- a filter on a BOUND VARIABLE rather than on a request field. *)
(* Reads the assignment, so it narrows which bindings the enclosing        *)
(* count/sum takes in rather than which events match.                      *)
(***************************************************************************)
CmpVarHolds(a, asg) ==
    /\ a.var \in DOMAIN asg
    /\ LET v == asg[a.var] IN
       /\ v.k = a.value.k
       /\ CASE a.cmp = "==" -> v.v = a.value.v
            [] a.cmp = "!=" -> v.v # a.value.v
            \* Integers only -- decimals are part of what that excludes. See CmpHolds for why.
            [] a.cmp = ">"  -> v.k = "n" /\ v.v > a.value.v
            [] a.cmp = "<"  -> v.k = "n" /\ v.v < a.value.v
            [] a.cmp = ">=" -> v.k = "n" /\ v.v >= a.value.v
            [] a.cmp = "<=" -> v.k = "n" /\ v.v <= a.value.v
            [] OTHER        -> FALSE

(***************************************************************************)
(* CEDAR'S `like`. One metacharacter: `*` matches any run of characters,   *)
(* including none. A pattern is a sequence of [wild, c] records because a  *)
(* wildcard is not a character and cannot be smuggled into a string.       *)
(*                                                                        *)
(* Named LikeMatches because `Matches` is the PREDICATE matcher above --   *)
(* a different question entirely, and one that already has the name.       *)
(*                                                                        *)
(* Backtracking, which the wildcard case needs: `*` either consumes        *)
(* nothing and the rest of the pattern must match here, or it consumes one *)
(* character and the SAME pattern must match the shorter string.           *)
(***************************************************************************)
RECURSIVE LikeMatches(_, _)
LikeMatches(pat, s) ==
    IF Len(pat) = 0
      THEN Len(s) = 0
      ELSE IF pat[1].wild
        THEN \/ LikeMatches(SubSeq(pat, 2, Len(pat)), s)
             \/ /\ Len(s) > 0
                /\ LikeMatches(pat, SubSeq(s, 2, Len(s)))
        ELSE /\ Len(s) > 0
             \* SubSeq, not s[1]: TLC refuses to apply a string as a function.
             /\ SubSeq(s, 1, 1) = pat[1].c
             /\ LikeMatches(SubSeq(pat, 2, Len(pat)), SubSeq(s, 2, Len(s)))

(***************************************************************************)
(* CEDAR'S `ipaddr`. An address is FOUR OCTETS, not a 32-bit number, and   *)
(* that is forced: TLC works in Java ints, so 208.4.4.0 -- 3489924096 --   *)
(* is not a value it can hold. Octets are 0..255 and never come close.     *)
(*                                                                        *)
(* `a.isInRange(ip("N/p"))` is true when the first p bits agree: p \div 8   *)
(* whole octets compared exactly, then the leading p % 8 bits of the next, *)
(* by integer division. TLA+ has no bit operations and needs none.         *)
(***************************************************************************)
InRange(addr, net, prefix) ==
    LET whole == prefix \div 8
        rest  == prefix % 8
    IN /\ \A i \in 1..whole : addr[i] = net[i]
       \* The partial octet, when the prefix does not land on a byte boundary. Dividing away the
       \* low 8 - rest bits leaves exactly the bits the prefix covers.
       /\ \/ rest = 0
          \/ addr[whole + 1] \div (2 ^ (8 - rest)) = net[whole + 1] \div (2 ^ (8 - rest))

InRangeHolds(a, dec) ==
    /\ a.field \in DOMAIN dec.input
    /\ LET v == dec.input[a.field] IN
       \* Kind "a" is an address: a four-element sequence of octets. A field holding anything
       \* else is not an address and the test is simply false, which is Cedar's behaviour for an
       \* extension call on the wrong type -- the condition does not hold, the policy does not
       \* apply.
       /\ v.k = "a"
       /\ InRange(v.v, a.net, a.prefix)

CmpHolds(a, dec) ==
    /\ a.field \in DOMAIN dec.input
    /\ LET v == dec.input[a.field] IN
       /\ v.k = a.value.k
       /\ CASE a.cmp = "==" -> v.v = a.value.v
            [] a.cmp = "!=" -> v.v # a.value.v
            \* ORDERING IS INTEGERS ONLY, and that includes excluding DECIMALS. This is the
            \* explanation for all THREE comparison helpers: `Cmp2Holds` and `CmpVarHolds`
            \* enforce the same rule and point here. One rule enforced in three places and
            \* explained in one is how the Cmp2Holds comment went stale the first time.
            \*
            \* The guide is
            \* explicit -- ordering "requires both sides to resolve to integers; otherwise the
            \* comparison is false", and a decimal "resolves but fails the integer conversion and
            \* yields false". This read `{"n", "d"}` and ordered decimals by their scaled value,
            \* which is a WRONG VERDICT rather than a missing feature.
            \*
            \* No corpus case compares a decimal with an ordering operator, so 919 agreeing pairs
            \* said nothing about it. The engine settles it: the same policy over a Long output
            \* ALLOWs and over a decimal output DENYs.
            [] a.cmp = ">"  -> v.k = "n" /\ v.v > a.value.v
            [] a.cmp = "<"  -> v.k = "n" /\ v.v < a.value.v
            [] a.cmp = ">=" -> v.k = "n" /\ v.v >= a.value.v
            [] a.cmp = "<=" -> v.k = "n" /\ v.v <= a.value.v
            [] OTHER        -> FALSE

RECURSIVE AtomHolds(_, _, _, _, _)
AtomHolds(a, i, trace, dec, asg) ==
    CASE a.op = "pred" -> Matches(a.pred, trace[i], dec, asg)
      [] a.op = "tp"   -> /\ a.var \in DOMAIN asg
                          /\ SameVal(asg[a.var], TP(i))
      \* Cedar's `like`, evaluated here rather than precomputed. A TLA+ string IS a sequence
      \* and TLC's Sequences implementation handles `Len`, `\o` and `SubSeq` on one; only
      \* function application is missing, which is why `Matches` reads a character as
      \* SubSeq(s, i, i) and never s[i].
      [] a.op = "like" -> /\ a.field \in DOMAIN dec.input
                          /\ LET v == dec.input[a.field] IN
                             v.k = "s" /\ LikeMatches(a.pattern, v.v)
      [] a.op = "inrange" -> InRangeHolds(a, dec)
      [] a.op = "cmp"  -> CmpHolds(a, dec)
      [] a.op = "cmp2" -> Cmp2Holds(a, dec)
      [] a.op = "cmpvar" -> CmpVarHolds(a, asg)
      \* A negated atom, at the SAME candidate event: "this happened and that did not".
      [] a.op = "not"  -> ~AtomHolds(a.args[1], i, trace, dec, asg)
      [] OTHER         -> \A k \in DOMAIN a.args : AtomHolds(a.args[k], i, trace, dec, asg)

(***************************************************************************)
(* THE TEMPORAL OPERATORS -- all past-time, because an authorizer decides  *)
(* now, from what has already happened.                                    *)
(***************************************************************************)
(***************************************************************************)
(* PARTITIONING, which an event schema's UNIVERSAL pin switches on.        *)
(*                                                                         *)
(* A pin declared on every event kind makes the leaf key-local: the trace  *)
(* is partitioned by the pinned key and a temporal operator sees only the  *)
(* decision's own partition. A pin on SOME kinds earns no isolation and    *)
(* stays global -- `term.keys` is empty there, and Mine is TRUE for every  *)
(* index, which is exactly the behaviour of a policy with no schema.       *)
(*                                                                         *)
(* It is invisible to `formerly`, `count` and `sum`: they are existential, *)
(* so restricting the candidates is the same as adding a conjunct. It is   *)
(* visible to `previous`, which means THE MOST RECENT match -- globally a  *)
(* foreign event can be that most recent one and fail, where partitioned   *)
(* it is skipped. Same policy, same trace, opposite verdicts.              *)
(***************************************************************************)
KeyOf(ev, k) ==
    \* `principal` and `resource` come from the event's scope envelope; every other key is a
    \* field the schema pins, carried in `pins` under its own name -- `session_id` from the
    \* reserved group, `tenant_id` from the request context. Partitioning on one of those
    \* confines a policy to its own session or tenant without the policy mentioning either.
    CASE k = "principal" -> ev.principal
      [] k = "resource"  -> ev.resource
      [] OTHER           -> ev.pins[k]

TermHolds(term, trace, upto, dec, asg) ==
    LET t == dec.time
        InWindow(i) == trace[i].time <= t /\ t - trace[i].time <= term.window
        Mine(i) == \A k \in DOMAIN term.keys :
                       SameVal(KeyOf(trace[i], term.keys[k]), KeyOf(dec, term.keys[k]))
    IN CASE
        \* No temporal operator at all: the body sees ONLY the decision's own timepoint.
        \* An aggregate written without a wrapper therefore counts what is happening now
        \* rather than what has happened, and `tp(v)` binds v to the decision's index.
        \* The window is meaningless here and is not consulted.
        term.op = "at" -> AtomHolds(term.atom, upto, trace, dec, asg)

        \* `formerly within W A` -- A held at some point in the window.
      [] term.op = "formerly" ->
            \E i \in 1..upto :
                /\ Mine(i)
                /\ InWindow(i)
                /\ AtomHolds(term.atom, i, trace, dec, asg)

        \* `previous within W A` -- the immediately preceding time point.
        \* The most recent event BEFORE the decision -- in the decision's own partition
        \* when a universal pin established one. With no keys `mine` is all of 1..upto-1 and
        \* `p` is upto-1, so this is the global reading unchanged.
        [] term.op = "previous" ->
            LET mine == {j \in 1..(upto - 1) : Mine(j)}
            IN /\ mine # {}
               /\ LET p == CHOOSE j \in mine : \A k \in mine : k <= j
                  IN /\ InWindow(p)
                     /\ AtomHolds(term.atom, p, trace, dec, asg)

        \* `A since within W B` -- B held in the window and A has held at every
        \* point after it; with `!A`, at none of them. Standard MFOTL Since.
        [] OTHER ->
            \E i \in 1..upto :
                /\ Mine(i)
                /\ InWindow(i)
                /\ AtomHolds(term.atom, i, trace, dec, asg)
                \* Foreign events are not just excluded as anchors; they are skipped by the
                \* "has held ever since" obligation too, which is what makes a negated since
                \* survive a foreign event sitting in the middle of the interval.
                /\ \A k \in (i + 1)..upto :
                      Mine(k) =>
                        IF term.leftNeg THEN ~AtomHolds(term.left, k, trace, dec, asg)
                                        ELSE AtomHolds(term.left, k, trace, dec, asg)

(***************************************************************************)
(* AGGREGATION                                                             *)
(*                                                                         *)
(* `count for (t: Timepoint), (x: String). where (phi)` is the number of   *)
(* DISTINCT ASSIGNMENTS to t and x under which phi holds -- not the number *)
(* of matching events. The two coincide when the only binder is a `tp`,    *)
(* which is the common idiom, and diverge as soon as a second variable is  *)
(* bound to a field that repeats.                                          *)
(*                                                                         *)
(* A binder's domain is its declared type: Timepoint ranges over the trace *)
(* indices visible at the decision, anything else over the generated value *)
(* domain TOGETHER WITH every scalar the trace carries. Both halves are    *)
(* needed and the second was missing: a property module builds its own     *)
(* session, so it can present a value the policy never names -- and a sum  *)
(* that skips such a value reports a smaller total rather than an unknown  *)
(* one. See `TraceScalars`. Finite either way, so TLC can enumerate it.    *)
(***************************************************************************)
RECURSIVE SumOver(_, _)
SumOver(S, k) ==
    IF S = {} THEN 0
    ELSE LET x == CHOOSE y \in S : TRUE
         IN (IF k \in DOMAIN x /\ x[k].k = "n" THEN x[k].v ELSE 0) + SumOver(S \ {x}, k)

Merge(outer, inner) ==
    [x \in (DOMAIN outer) \union (DOMAIN inner) |->
        IF x \in DOMAIN inner THEN inner[x] ELSE outer[x]]

RECURSIVE CondHolds(_, _, _, _, _, _)

Satisfying(agg, trace, upto, dec, asg, values) ==
    LET names  == {b.name : b \in {agg.binders[i] : i \in DOMAIN agg.binders}}
        Dom(n) == LET b == CHOOSE x \in {agg.binders[i] : i \in DOMAIN agg.binders} : x.name = n
                  IN IF b.type = "Timepoint" THEN {TP(i) : i \in 1..upto} ELSE values
    IN { inner \in [names -> values \union {TP(i) : i \in 1..upto}] :
            /\ \A n \in names : inner[n] \in Dom(n)
            /\ CondHolds(agg.cond, trace, upto, dec, Merge(asg, inner), values) }

AggValue(agg, trace, upto, dec, asg, values) ==
    LET sats == Satisfying(agg, trace, upto, dec, asg, values)
    IN IF agg.kind = "count" THEN Cardinality(sats) ELSE SumOver(sats, agg.over)

Compare(lhs, op, rhs) ==
    CASE op = "==" -> lhs = rhs
      [] op = "!=" -> lhs # rhs
      [] op = ">=" -> lhs >= rhs
      [] op = "<=" -> lhs <= rhs
      [] op = ">"  -> lhs > rhs
      [] OTHER     -> lhs < rhs

CondHolds(c, trace, upto, dec, asg, values) ==
    CASE c.op = "true" -> TRUE
      [] c.op = "term" -> TermHolds(c.term, trace, upto, dec, asg)
      [] c.op = "not"  -> ~CondHolds(c.args[1], trace, upto, dec, asg, values)
      [] c.op = "and"  -> \A i \in DOMAIN c.args :
                              CondHolds(c.args[i], trace, upto, dec, asg, values)
      \* Cedar's `||`. Only reachable from a policy body, since a temporal condition has no
      \* disjunction of its own.
      [] c.op = "or"   -> \E i \in DOMAIN c.args :
                              CondHolds(c.args[i], trace, upto, dec, asg, values)
      \* A real existential: some assignment to the bound variable makes the body hold.
      \* `Satisfying` already enumerates exactly those assignments for an aggregate, so
      \* this is the same set being non-empty.
      [] c.op = "exists" -> Satisfying(c.agg, trace, upto, dec, asg, values) # {}

      \* `exists (n: T). (AGG == n && n CMP k)` -- the idiom the corpus uses for most
      \* aggregations, which says nothing more than `AGG CMP k`.
      [] OTHER         -> Compare(AggValue(c.agg, trace, upto, dec, asg, values),
                                  c.cmp, c.value)

(***************************************************************************)
(* THE DECISION -- Cedar's model, which Dogwood keeps: deny by default,    *)
(* forbid overrides permit.                                                *)
(***************************************************************************)
PolicyMatches(p, trace, upto, dec, values) ==
    \* The actions this policy applies to. EMPTY means every action -- a bare `action` scope
    \* constrains nothing -- and a set with more than one is `action in [A, B]`.
    /\ p.actions = {} \/ dec.action \in p.actions
    /\ CondHolds(p.cond, trace, upto, dec, << >>, values)

\* Every scalar the trace itself carries, from the input and output of every event.
\*
\* AN AGGREGATE BINDER HAS TO SEE THESE. `sum a for (a: Long). where (... { input.amount: a })`
\* binds `a` by matching events, so a value present in the trace and absent from the generated
\* domain is a value the sum silently skips -- and a total that omits a term is not reported as
\* uncertain, it is reported as a smaller number. That is a wrong verdict with no symptom.
\*
\* It does not arise for the built-in questions, whose traces are assembled FROM the domain, which
\* is why it went unnoticed: every value in such a trace is in `values` already. It arises for a
\* property module, which builds its own session and is supposed to be able to state one about
\* values the policy never names -- the whole reason `PolicyUnderTest` offers no `Inputs`.
\*
\* Adding to the binder's domain can only make MORE assignments satisfying, never fewer, so this
\* cannot turn a real finding into a missed one. It is checked against the corpus like everything
\* else here.
TraceScalars(trace) ==
    UNION { {trace[i].input[f]  : f \in DOMAIN trace[i].input}
          \union {trace[i].output[f] : f \in DOMAIN trace[i].output}
          : i \in DOMAIN trace }

Decide(trace, policies, idx, values) ==
    LET dec  == trace[idx]
        seen == values \union TraceScalars(trace)
        hit  == {k \in DOMAIN policies : PolicyMatches(policies[k], trace, idx, dec, seen)}
    IN /\ \E k \in hit : policies[k].effect = "permit"
       /\ ~\E k \in hit : policies[k].effect = "forbid"

(***************************************************************************)
(* WHICH policies decided, not merely what was decided -- Cedar's         *)
(* "determining policies". The matching forbids when any forbid matches,  *)
(* the matching permits otherwise, and the empty set when a deny is by    *)
(* default.                                                               *)
(*                                                                        *)
(* Note this is NOT the set of policies that matched. At a decision where *)
(* an unconditional permit and a forbid both match, only the forbid       *)
(* determines, and the permit -- which did match -- is not listed.        *)
(*                                                                        *)
(* A model can reach the right verdict through the wrong rule. Only this  *)
(* tells the two apart.                                                   *)
(***************************************************************************)
Determining(trace, policies, idx, values) ==
    LET dec  == trace[idx]
        hit  == {k \in DOMAIN policies : PolicyMatches(policies[k], trace, idx, dec, values)}
        bans == {k \in hit : policies[k].effect = "forbid"}
    IN IF bans # {} THEN bans ELSE {k \in hit : policies[k].effect = "permit"}

CaseAgrees(c) ==
    /\ \A d \in DOMAIN c.oracle :
        \/ Decide(c.trace, c.policies, d, c.values) = c.oracle[d]
        \/ Print(<<"DISAGREEMENT", c.name, "at decision index", d,
                   "model says", Decide(c.trace, c.policies, d, c.values),
                   "dogwood says", c.oracle[d]>>, FALSE)
    \* Attribution, wherever the oracle records it. The unit corpus's fixtures record only
    \* true/false, so `rules` is empty there and this conjunct is vacuous -- the examples
    \* corpus is the one that carries rule ids.
    /\ \A d \in DOMAIN c.rules :
        \/ Determining(c.trace, c.policies, d, c.values) = c.rules[d]
        \/ Print(<<"DISAGREEMENT (attribution)", c.name, "at decision index", d,
                   "model fired", Determining(c.trace, c.policies, d, c.values),
                   "dogwood fired", c.rules[d]>>, FALSE)

Agree == \A i \in DOMAIN Cases : CaseAgrees(Cases[i])

=============================================================================
