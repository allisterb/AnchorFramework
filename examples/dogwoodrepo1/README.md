# Write-after-read, as Dogwood's agent skill prints it and as Dogwood's guide does

Dogwood ships an agent skill, `autoformalize-policies`, that turns a prose authorization rule into
a `.dw` policy. Its one worked example of a history-dependent policy is the **write-after-read**
rule. That is also the Dogwood guide's flagship temporal example, and the two do not print the same
policy.

| | event the Write is gated on | comment above the policy |
|---|---|---|
| the guide, `04-temporal-expressions.md`, and its runnable bundle `dogwood-docs/examples/write_after_read_formerly/` | `Read::response` | "the same user **successfully** read the same document" |
| the skill, `.claude/skills/autoformalize-policies/SKILL.md`, section 2b | `Read::request` | "this user read the same document" |

The guide's own gloss of its version is "this same user successfully read this same document".
`::request` is the *attempt*. Under Dogwood's default event schema it is recorded whatever the
outcome, and the outcome follows as `::response` (completed) or `::error` (denied, or failed). So
the skill's version is satisfied by a Read that was **refused**.

**Scope note.** This is not a defect in the Dogwood engine, which evaluates both policies exactly as
written. It is about the example an agent is taught from. The skill tells its reader to match the
guide's corpus examples. Its copy of this one has drifted, and in the direction that grants more.

All sources are at the pinned submodule commit `c6237c88` (see the reference ledger). Dogwood is
© Amazon.com Inc, Apache 2.0. `schema.cedarschema` is copied unchanged from
`dogwood-docs/examples/write_after_read_formerly/`.

## What was found

| | skill's version | guide's version |
|---|---|---|
| alice's Read of a document is **denied**, then she writes it | **ALLOW** | DENY |
| alice's Read is allowed but **fails**, then she writes it | **ALLOW** | DENY |
| a slow Read (asked at 0, completed at 600), then a Write at 3700 | **DENY** | ALLOW |
| the guide's own four cases: completed read, other document, past the hour, no read | as the guide says | as the guide says |

Every verdict is reached by Anchor's model **and** by the Dogwood engine, and the two agree on all
of them.

The first row is the one that matters: **a user refused read access to a document can write it, by
attempting the read first.** The third row cuts the other way: the window runs from when the Read
was asked, not when it completed. That shows the two policies differ in meaning, not just in
strictness.

## How it was checked

**Each version is checked as a set, beside read access control we added** (marked `// ours` in
both files): anyone may read, except one restricted document. Without a rule permitting `Read`, the
guide's version could never fire, because nothing can have a `Read::response` if no Read is ever
allowed. Anchor would rightly report it VACUOUS. The aws examples add their supporting reads for the
same reason.

**Three independent checks, all of which agree:**

1. **Rule by rule, exhaustively** (`findings.md`). Every rule in both sets is *live*: it can grant
   something, and deleting it changes some verdict. The built-in checks cannot tell the two
   versions apart. Each is a working rule. They differ only relative to what was meant.
2. **A stated intention** (`SuccessfulRead.tla`, and `SuccessfulReadGuide.tla`, the same claims word
   for word, against the guide's set):
   - no Write after a denied Read;
   - no Write after a failed Read;
   - no Write with no Read;
   - and, as a control, a Write *is* allowed after a completed Read.

   The skill's set breaks the first, and the engine confirms the witness. The guide's set holds all
   four. On the guide's set, the decision probe confirms the Write decision varies, and mutation
   scoring catches every mutation of the write rule. The five mutants that survive are all
   mutations of our read rules, which these claims are not about.
3. **A decision table** (`tables/`), written from the guide's sentence rather than from either
   policy: seven sessions, 13 decisions. The guide's set agrees with all 13. The skill's set agrees
   with 10, and the other 3 are marked `finding`. Results are in `tables/*.result.txt` and `.json`.

## Reproduce

```bash
./anchor check examples/dogwoodrepo1 --full --no-llm
python src/checker/table.py examples/dogwoodrepo1/skill-set.dw --table examples/dogwoodrepo1/tables/skill-set.table --policy-schema examples/dogwoodrepo1/schema.cedarschema
python src/checker/table.py examples/dogwoodrepo1/guide-set.dw --table examples/dogwoodrepo1/tables/guide-set.table --policy-schema examples/dogwoodrepo1/schema.cedarschema
```

Or with the Dogwood CLI alone, no Anchor involved. Both sets validate cleanly, and
`traces/skill-set-SuccessfulRead/witness/` holds everything `dogwood replay` needs for the denied-read
session: the trace, the policy set, the event schema, and an action schema:

```bash
dogwood validate skill-set.dw --policy-schema schema.cedarschema     # OK: validation passed
cd traces/skill-set-SuccessfulRead/witness
dogwood replay --policy-schema generated.cedarschema --event-schema pinned.dwschema --trace NoWriteAfterADeniedRead.log skill-set.dw
```

## Caveats

- **Dogwood's default event schema**, where history is per principal. Under AgentCore's
  session-pinned schema the request/response distinction is the same.
- **The read rules are ours.** Any rule that can deny a Read gives the same result. The point needs
  only that a Read *can* be denied or fail, which in a real deployment it can.
- **A property module fixes its histories.** The sessions in `SuccessfulRead.tla` include the denied
  Read's `::error` event outright, rather than deriving it from the read rules. The decision table
  is the check that takes the read rules' own verdicts into account. It reaches the same answer.

## Files

| | |
|---|---|
| `skill-set.dw` | the skill's policy, verbatim, plus our read rules |
| `guide-set.dw` | the guide's policy, verbatim, plus the same read rules |
| `schema.cedarschema` | Dogwood's own action schema for this example, unchanged |
| `SuccessfulRead.tla` / `.cfg` | the stated intention, against `skill-set.dw` |
| `SuccessfulReadGuide.tla` / `.cfg` | the same claims against `guide-set.dw`: the control |
| `tables/` | the decision tables and their results, for both sets |
| `findings.md`, `findings.html`, `results.json`, `traces/` | the report `anchor check` generated |

## Reproduce with Dogwood alone, from Dogwood's own files

The shortest reproduction: no Anchor, no read rules of ours, three files. Run from a Dogwood
checkout.

`policy.dw` is the skill's section 2b, verbatim:

```
// Permit a Write only if this user read the same document within the last hour.
@id("write_after_read")
permit ( principal, action == Drupe::Action::"Write", resource )
when temporal {
    formerly within 1h Drupe::Action::"Read"::request{
        input.user: context.input.user,
        input.document: context.input.document
    }
};
```

`schema.cedarschema` is `dogwood-docs/examples/write_after_read_formerly/schema.cedarschema`,
unchanged (the copy in this directory is the same file). `trace.log` has alice's Read of doc1
refused, then her Write of doc1:

```
@0 scope(principal: Drupe::OAuthUser::"alice", resource: Drupe::Gateway::"gw1") request_context(input: { document: "doc1", user: "alice" }) Drupe::Action::"Read"::request(input: { document: "doc1", user: "alice" }, callerPrincipal: Drupe::OAuthUser::"alice", callerResource: Drupe::Gateway::"gw1", requestId: "u1")
@1 scope(principal: Drupe::OAuthUser::"alice", resource: Drupe::Gateway::"gw1") Drupe::Action::"Read"::error(input: { document: "doc1", user: "alice" }, callerPrincipal: Drupe::OAuthUser::"alice", callerResource: Drupe::Gateway::"gw1", requestId: "u1")
@10 scope(principal: Drupe::OAuthUser::"alice", resource: Drupe::Gateway::"gw1") request_context(input: { document: "doc1", user: "alice" }) Drupe::Action::"Write"::request(input: { document: "doc1", user: "alice" }, callerPrincipal: Drupe::OAuthUser::"alice", callerResource: Drupe::Gateway::"gw1", requestId: "u2")
```

```
$ dogwood validate policy.dw --policy-schema schema.cedarschema
OK: validation passed with no errors or warnings.

$ dogwood replay policy.dw --policy-schema schema.cedarschema --trace trace.log
@0 (time point 0): DENY
@10 (time point 1): ALLOW  [rules: 0]

$ dogwood replay dogwood-docs/examples/write_after_read_formerly/policy.dw --policy-schema schema.cedarschema --trace trace.log
@0 (time point 0): DENY
@10 (time point 1): DENY
```

The Read is denied, and the Write is allowed anyway. The guide's version, run from the repository
unchanged, denies it. Output as of 2026-10-14, from the engine built at the pinned `c6237c88`.
