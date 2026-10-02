# The article's decision tables, checked

For six of its seven policies, the AWS blog post prints a table of **Expected result**s. Each file
here holds one of them, in the conformance format of
[`tests/policies/agentcore/`](../../../tests/policies/agentcore/README.md): the policy as published,
verbatim, and each table row as a session (`//|` lines) with the decision the article expects.

| file | holds |
|---|---|
| `01-…` to `07-…` | each published policy alone, against its own table |
| `00-published-set.dw` | `../agent-policy.dw`, the six together, against every DENY row the article prints for a trade |
| `90-fixed-set.dw` | `../fixed/agent-policy.dw` against every row of every table |
| `blog.cedarschema` | the action schema for the article's tools. **Ours**: the article gives none. Its header states the two assumptions it makes |

**A row marked `finding`** is one where the policy as published does the opposite of what the article
says. The verdict on the line stays the article's; the marker says the policy does otherwise, and
both checkers are held to that. A finding that stopped reproducing would fail the run, just as an
unmarked disagreement would.

**Sources, per decision:** `aws-table` is a row of the article's table; `aws-prose` is the article's
text, as exact as a table ("Each approval covers exactly one execution"); `ours` is a decision the
tables assume without stating, such as the read-only lookup a row depends on being allowed. Timings
are ours where a table's are qualitative, and input values are ours where a table names none.

```bash
python tests/strands/agentcore_replay.py --suite examples/aws1/tables       # the Dogwood engine
python tests/strands/agentcore_conformance.py --suite examples/aws1/tables  # Anchor's model
```

2026-10-02: **131 decisions, all reproduced by both, 16 of them findings.** Fifteen are in the
published policies. The sixteenth is the fixed set's one remaining finding, the response-recording
delay, which no policy can close. See [`../README.md`](../README.md).
