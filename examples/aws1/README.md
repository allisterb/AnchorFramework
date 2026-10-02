# The AgentCore temporal policies, checked

The policies from the AWS blog post [*Securing AI agents with temporal policies in Amazon Bedrock
AgentCore*](https://aws.amazon.com/blogs/machine-learning/securing-ai-agents-with-temporal-policies-in-amazon-bedrock-agentcore/),
transcribed here and run through Anchor.


**Scope note before anything else.** These are code snippets from a blog post explaining ideas one
at a time, not a deployed policy set. Nothing below is a vulnerability in a product.



## The files

| | |
|---|---|
| `01-workflow-sequencing.dw`, `02-output-to-input.dw`, `03-data-freshness.dw`, `04-cumulative-budget-cap.dw`, `05-human-approval.dw`, `07-trust-decay.dw` | the article's policies, one per file, as published. Six of the seven — see below for why 6 is missing |
| `agent-policy.dw` | the same policies as a **set**, with the read actions permitted, which is how they would be deployed |
| `TrustDecay.tla` / `.cfg` | what policy 7 is *supposed* to mean, stated as invariants |
| `TradeGate.tla` / `.cfg` | what the trade protections are supposed to mean *together* |
| `traces/` | one directory per run: the generated model, the config it used, the raw TLC output, and a README with the command to re-run it. Named `<policy>` for a derived run and `<policy>-<module>` for a property one. Regenerated wholesale by `anchor check <directory> --full` |
| [`questions.md`](questions.md) | the five questions in plain language, as somebody would actually ask them |
| [`transcript.md`](transcript.md) | the agent answering all five, with **every tool call and its full reply** |
| `TrustDecay10.tla` / `.cfg` | the ten-minute claim on its own, because TLC stops at the first violated invariant |
| [`fixed/`](fixed/README.md) | a proposed fix for each finding, checked against the same property modules |

Six of the seven policies in the article are here. Policy 6 is not here because it does not parse — in Dogwood, not in Anchor. As published it
reads:

```dogwood
AgentCore::Action::"execute_buy"{
    stock_symbol: context.input.stock_symbol, eventResource: resource}
```

The reference implementation rejects that:

```
$ dogwood check-parse policy6.dw
× unexpected token `{`, expected comparison operator
```

A predicate needs the `::<kind>` segment after the quoted action, and a field needs its group
prefix — `AgentCore::Action::"execute_buy"::request{ input.stock_symbol: … }` parses. Both are
single-token omissions in the article's listing rather than anything about the language, but
repairing a published policy and then reporting findings about it would be reporting findings
about our repair. It stays out until the text can be checked against the article itself.

**Also dropped**, in every file here: the `resource == AgentCore::Gateway::<ARN>` scopes, and the
`eventResource: resource` joins that go with them. **Both are correct AgentCore, and required by
it**: AgentCore's [temporal policy examples](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies-temporal.html)
make `eventResource: resource` mandatory in every predicate, and scope every policy to its gateway.
They are dropped because Anchor does not yet model AgentCore's event schema, and refuses both rather
than guessing at them (see
[`the-modelled-subset`](../../src/Anchor.MCPServer/knowledge/the-modelled-subset.md)). Every policy
in the article scopes to the same single gateway, so with one gateway in play, dropping the scope
and the join changes nothing the checks can see. Recorded so the difference from the published text
is not mistaken for a finding.

AgentCore's events also name their scope fields differently from Dogwood's default event schema:
`eventPrincipal` and `eventResource`, where Dogwood's default has `callerPrincipal` and
`callerResource`. So the open-source `dogwood validate`, run with its default schema, rejects the
article's joins (`mentions field eventResource, which is not declared on that event`) where
AgentCore accepts them. That is a difference of event schema, not an error in the article.

Note that most policies are vacuous when evaluated alone. This is expected and worth seeing: a
permit gated on `X::response` cannot fire where nothing permits `X`. 

```
./anchor check examples/aws1/03-data-freshness.dw --attempts 4
...

03-data-freshness.dw: 1 permit(s), 0 forbid(s), bound 4 attempts

  permit #1  action == execute_trade VACUOUS   no session of up to 4 attempts makes it grant
      because: formerly within 30s get_market_price::response

VACUOUS permit #1
```

A permit gated on `get_market_price::response` cannot fire in a file where nothing permits
`get_market_price`: the call is denied, AgentCore records an `::error` rather than a `::response`,
and the gate never opens. That is a composition effect, not a defect in the article. We need to evaluate the entire policy set:


```bash
./anchor check examples/aws1/agent-policy.dw --attempts 4
```

```
  permit #5  action == rebalance_portfolio live   witness: get_client_profile -> load_portfolio -> rebalance_portfolio
      1. get_client_profile (profile_id = 1)  allowed
      2. load_portfolio     (profile_id = 1)  allowed
      3. rebalance_portfolio(profile_id = 1)  allowed
  permit #6  action == execute_trade       live   witness: get_client_profile -> execute_trade
  permit #7  action == execute_trade       live   witness: get_market_price -> execute_trade

every rule is load-bearing within 4 attempts.
```

The three-hop chain is found without anyone describing it. And that is the whole of what the
derived property questions can say: every rule fires, none is redundant, nothing is dead.

Not every fragment is vacuous on its own, though, and one of the exceptions matters: policy 7 is
live alone only because its condition is inverted, which is finding 1 below.

## What was found

| | |
|---|---|
| **Policy 7 is inverted relative to its own description** | it permits writes *only while the advisor is absent*, which is the reverse of the sentence beside it. Machine-checked, with counterexamples |
| **The two trade protections are alternatives, not requirements** | a trade goes through on a fresh price with **no profile check at all** — precisely the prompt-injection case one of them exists to prevent |

Both findings have a proposed fix in [`fixed/`](fixed/README.md), checked against the same
property modules with every claim listed: all of them hold, and every rule is live.

## 1. Policy 7 says the opposite of what it does

The article's text:

> "After 15 minutes without advisor interaction, the agent loses access to write operations."
> … "If the advisor walks away, the agent naturally converges toward read-only behavior."

The policy beside it:

```
permit (principal, action == ...execute_trade..., resource)
unless temporal {
    formerly within 15m AgentCore::Action::"interact_advisor"::response{...}
};
```

`unless { B }` blocks the rule when `B` holds — [Dogwood's own
guide](../../ext/dogwood/dogwood-docs/guide/02-policy-language.md): *"An `unless` clause blocks the
rule when its body holds."* So this permits the trade when the advisor has **not** interacted
within 15 minutes. Trust decays into *more* access, not less.

`TrustDecay.tla` states the sentence as three invariants. All three break:

| claim | | counterexample |
|---|---|---|
| `LosesWriteAfter15m` | **BROKEN** | `gap = 960` — 16 minutes after the advisor left, the trade is **allowed** |
| `KeepsWriteWhileAdvisorEngaged` | **BROKEN** | `gap = 1` — one second after the advisor interacted, the trade is **denied** |
| `LosesWriteAfter10m` | **BROKEN** | `gap = 960` — the tighter deadline fails the same way |

```bash
python src/checker/properties.py examples/aws1/07-trust-decay.dw --property examples/aws1/TrustDecay.tla
```

**Nothing else in the pipeline catches this.** It parses. It type-checks. `dogwood validate` accepts
it. The derived run reports *"every rule is load-bearing"*. The rule fires — a permit that fires is
a permit that fires, whichever way round its condition reads. Only a statement of intent, checked,
separates the two.

### Why this one needs a hand-built session

`gap` is in **seconds**, because the evaluator compares an event's timestamp against the window
width directly. The derived exploration walks sessions whose events are one second apart, so a
15-minute window can **never age out** there: within any three-attempt session every prior event is
inside it. Only a trace with chosen timestamps can put a decision on the far side of a window, which
is what `Ev(action, kind, input, output, time)` in the generated module is for.

That is a real limit on the derived questions and it is stated rather than worked around: they
bound the number of events, not elapsed time.

## 2. The two trade protections are alternatives

The article introduces these as distinct protections:

> **output-to-input integrity** — "prevents an attacker from using prompt injection to steer the
> agent to trade against a different client's portfolio"
> **data freshness** — "the agent cannot act on stale quotes"

Read as a list of requirements, that is a conjunction. Written as two `permit` rules on the same
action, they are alternatives: Cedar permits by positive match, so **either one firing is enough**.

`TradeGate.tla` states it both ways and asks:

| claim | |
|---|---|
| `BothIsAllowed` | holds — the intended path is not shut |
| `NothingAllowsNoTrade` | holds — with neither prerequisite, no trade |
| `RequiresBothChecks` | **BROKEN** at `prereq = "profileOnly"` |
| `ProfileAloneIsNotEnough` | **BROKEN** — a trade on a profile load alone, against a 24-hour-stale price |
| `FreshPriceAloneIsNotEnough` | **BROKEN** — a trade on a fresh price alone, **with no profile check at all** |

The last one is the one that matters: it is exactly the scenario the integrity policy was written to
prevent, reachable because the freshness policy grants independently.

**The two positive claims holding is what makes the three failures worth reading.** A property
module that broke everything would more likely be wrong about the policy than the policy about
itself.

```bash
python src/checker/properties.py examples/aws1/agent-policy.dw --property examples/aws1/TradeGate.tla
```

## 3. Asking the agent instead

The same question, put to the agent rather than the CLI:

```bash
python src/agent/policy_agent.py examples/aws1/07-trust-decay.dw \
  --ask "This policy is supposed to mean: 'After 15 minutes without advisor interaction, the
         agent loses access to write operations.' I have written that claim as a TLA+ property
         module at examples/aws1/TrustDecay.tla. Does the policy actually mean that?"
```

> The policy `examples/aws1/07-trust-decay.dw` does not mean what your TLA+ property module claims
> it should. … the model check found that this invariant is violated. Specifically, the
> `KeepsWriteWhileAdvisorEngaged` invariant is broken in an initial state where `gap = 1`. …
>
> Please note that this check was performed assuming an **UNPINNED reading** (a global trace),
> because no event schema was provided. If your policy is deployed with a schema that partitions
> history by principal (which is the shipped default), a rule that might appear to be live here
> could behave differently in deployment.

*Recorded before 0.1.3, when a check with no event schema used the unpinned reading. The default is
now Dogwood's own, `callerPrincipal` pinned, and the same caveat now names that reading instead.*

**The second paragraph was not asked for.** The system prompt does not restate the caveats — it
says a knowledge base exists and must be consulted before reporting a verdict. The agent read
[`event-schemas-and-pins`](../../src/Anchor.MCPServer/knowledge/event-schemas-and-pins.md) and
qualified its own answer. That is the experiment [`src/agent/README.md`](../../src/agent/README.md)
describes, and this is it passing on a policy nobody wrote for it.

## Everything above, from one command

```bash
anchor check examples/aws1 --full
```

Finds the policy sets by globbing, pairs each `.tla` with the policy set its header names, runs every
check, then puts the questions in [`questions.md`](questions.md) to the agent. Without `--full` it
runs only the rule-by-rule checks, prints them, writes nothing, and lists what `--full` would add. Writes
[`findings.md`](findings.md), `findings.html`, `results.json`, [`transcript.md`](transcript.md)
and `traces/`. Exits **1** when there is something to look at, so it can gate a pipeline; **3** when
the run could not happen at all.

`--no-llm` does the checks and the report without asking an LLM anything — most of the value,
none of the cost, and the part that belongs in CI. `--output-dir findings` writes elsewhere.

**What is automated and what is not.** Running every check is automated. Deciding what a policy was
supposed to mean is not, and a directory with no `.tla` modules gets a report that says so in those
words rather than one that looks like a pass.

## Reproducing

Each directory under `traces/` holds the generated `PolicyUnderTest.tla`, the evaluator, the config
each run used and the raw TLC output, plus a README with the exact `java -cp … tlc2.TLC` command.
Nothing here has to be taken on trust.

```bash
python src/checker/properties.py examples/aws1/agent-policy.dw --attempts 4 --keep /tmp/out
```

**TLC stops at the first violated invariant**, so a run reports one broken claim however many
the `.cfg` names. `TradeGate.cfg` names only `FreshPriceAloneIsNotEnough`, the one that matters, and
the report lists the other four as defined but not checked; the table in section 2 comes from
checking each claim on its own, with a one-line `.cfg` per claim. `fixed/TradeGate.cfg` names all
five, because against the fixed policy set none of them breaks.

## What this example is evidence for

Three kinds of question, and only the third caught anything:

1. **Does it parse and type-check?** `dogwood validate`. Passes.
2. **Is any rule inert?** The derived questions. Everything live, in the set as deployed.
3. **Does it mean what its author said?** Only an author can state this, and it is the only one that
   found anything.

The survey literature calls the gap between (2) and (3) the *user-intent formalization gap* and
reports it as unsolved. It is not solved here either — nothing can check prose against a policy.
What is demonstrated is narrower and still useful: **once the intent is written down formally, the
mismatch is found mechanically, in seconds, with a counterexample.** The writing-down is the part
that needs a person.
