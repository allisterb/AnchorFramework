# Evaluating Anchor

Anchor needs four runtimes — .NET, a JVM, CPython and a Rust binary — so there is a container that
carries all of them. Nothing is installed on your machine and nothing is cloned.

## Getting it

```bash
docker pull public.ecr.aws/v4q7x8t1/anchor:latest
docker run --rm public.ecr.aws/v4q7x8t1/anchor:latest version
```

The image is on Amazon ECR Public, so pulling it needs no AWS account or login. `public.ecr.aws/v4q7x8t1/anchor:0.1.2`
pins the version this page describes. It is about **350 MB** to download, and it ships the worked
examples described below, so every command on this page runs with no other setup.

It is built for both `linux/amd64` and `linux/arm64` under the same tag, so Docker pulls the one
that matches your machine and Apple Silicon runs it natively, with no `--platform` flag.

Docker Hub's `allisterb/anchor:0.1.0` is the image submitted to the hackathon, kept unchanged while
judging runs. It predates the input scanner and `findings.html` described below, and is amd64 only.

The entry point is the `anchor` launcher, so arguments after the image name are the verb and its
options — the container behaves like the command, not like a service.

```bash
docker run --rm public.ecr.aws/v4q7x8t1/anchor:latest help
```

The samples live at `/app`, which is why the commands below pass `-w /app`. To check **your own**
policy instead, mount your directory and drop that flag:

```bash
docker run --rm -v "$PWD:/work" public.ecr.aws/v4q7x8t1/anchor:latest check my-policy.dw
```

Your working directory is mounted at `/work`, which is the container's working directory, so paths
read the way they do on your machine and output lands back on it. On Linux add
`--user "$(id -u):$(id -g)"` so files come back owned by you.

---

## What this is

A Dogwood policy can parse, type-check, validate against its schema, and still not mean what its
author meant. Anchor asks two different kinds of question about one — the first needs nothing from
you, the second needs you to say what the policy was *for*.

Three things are worth knowing before you read a verdict:

* **A bounded answer is stated as bounded.** Nothing here claims a proof over all inputs.
* **`VACUOUS` is the answer that must never be wrong**, because it tells somebody a control is dead
  and the obvious next step is to delete it. It is falsification-tested, and anything that is not an
  answer — a parse error, an unsupported construct — refuses rather than reporting vacuous.
* **A finding against a property a model drafted is weaker evidence than one against a property a
  person wrote.** Every report says which it was.

---

## 1. The questions that need nothing from you  — *5 seconds, no API key*

```bash
docker run --rm -w /app public.ecr.aws/v4q7x8t1/anchor:latest check tests/policies/dead_forbid.dw
```

```
  permit #1  action == Trade         live      witness: Trade
  forbid #2  action == Approve       DEAD      deleting it changes no verdict in any session
```

Two rules, both well-formed. `Approve` has no permit, so default-deny already refuses it and the
`forbid` changes no verdict in any session — it reads like a control and is not one. Nothing about
either rule is impossible in isolation, which is why a per-rule validator has nothing to say:

```bash
docker run --rm -w /app --entrypoint /app/bin/dogwood public.ecr.aws/v4q7x8t1/anchor:latest \
    validate --policy-schema tests/policies/anchor.cedarschema tests/policies/dead_forbid.dw
```

```
OK: validation passed with no errors or warnings.
```

That is the reference implementation, in the same image, agreeing the file is fine. The difference
is not analysis versus none — it is **one rule at a time versus the whole rule set**.

This mode runs three questions per rule, each answered with a concrete witness session or a bounded
no: *can this permit ever grant anything*, *is this rule doing anything*, and with `--against`,
*do two versions of a policy decide differently*.

## 2. The question that needs you  — *12 seconds, no API key*

This is the finding the project exists for, and it comes from a real AWS article's example.

```bash
docker run --rm -w /app public.ecr.aws/v4q7x8t1/anchor:latest \
    check examples/aws2/agent-policy.dw --property examples/aws2/CumulativeCap.tla --max-fields 8
```

```
BROKEN  Invariant ARefusedAttemptDoesNotConsumeTheBudget is violated by the initial state:
    scenario = "afterRefused"
```

The requirement, quoted from the article, is *"block a transfer if the total amount **transferred**
in the past 12 hours would exceed $50,000."* The policy sums `::request` — the **attempt**. Under
AgentCore's convention an attempt is recorded whether or not it succeeded, so one refused $60,000
request blocks every transfer for twelve hours having moved no money.

Run mode 1 on that same file and all seven rules report **live**. The rule is live. It is also
wrong. That gap is the whole argument, and closing it took somebody writing down what the policy was
supposed to mean.

## 3. What a claim will actually catch  — *instant*

```bash
docker run --rm -w /app public.ecr.aws/v4q7x8t1/anchor:latest explain tests/policies/firewall.tla
```

Per claim: what it **forbids**, which states it will be checked in, and how many of those its
condition even applies to. No model checker runs. Read the `forbids` lines before a check rather
than after — each one is the only thing its claim can catch, and a claim whose condition applies to
nothing will pass having tested nothing.

## 4. A whole directory  — *minutes*

```bash
docker run --rm -v "$PWD:/work" -w /app public.ecr.aws/v4q7x8t1/anchor:latest \
    check examples/aws1 --no-model --output-dir /work/aws1
```

Every `.dw` paired with the `.tla` module whose header names it, writing `findings.md`,
`findings.html`, `results.json` and `traces/` into `./aws1` on your machine. `--output-dir` is what
brings them out: without it they are written inside the container, and go when it does. It exits 1,
because the audit has findings.

`--no-model` is what keeps this mode mechanical. `examples/aws1` also holds a `questions.md`, and
without the flag the audit asks a model those questions as well, which needs the key set up under
the agent modes below; with no key, each question fails and the rest of the audit is unaffected.

`examples/aws1` and `examples/aws2` already contain the committed output of this audit, so you can
compare. Expect three differences: the committed reports predate the input scan, so they have no
**Input scan** line; they were written with the questions answered; and each `Run it yourself`
names wherever your copy was written, which from inside the container is `/work/aws1`, i.e. `./aws1`
on your machine.

A directory audit scans its inputs before anything reads them; see the agent modes below.

`findings.html` is the audit as one page: each broken claim drawn as the session that breaks it,
with the reference engine's verdict on every decision and the rule that decided it. It is a single
file that opens straight from disk. Because it quotes policy text, it runs nothing but its own inlined
renderer: its Content-Security-Policy allows that one script by hash, and nothing else.

## 5 and 6. The agent modes  — *needs an API key*

The first four modes are mechanical (the fourth with `--no-model`, as shown): no model is involved,
and nothing a model said can change a verdict. The last two are where an agent writes the formal artifact.

**Before either shows a model anything, it scans the inputs.** A policy under analysis is often one
nobody trusts, and its comments and string literals reach the model. `anchor scan` is the same check
on its own — instant, and no key:

```bash
docker run --rm -v "$PWD:/work" public.ecr.aws/v4q7x8t1/anchor:latest scan my-policies/
```

It reports, by severity, hidden and reordering characters, names spelled with look-alike letters,
instructions aimed at a model, markup, terminal escapes and encoded payloads. A high finding stops
`auto` and `hitl` with exit 2, before any model is called. `--allow-flagged-input` proceeds anyway
for a finding you have read — a comment that *discusses* prompt injection, say — and the report
records that it did. Like `findings.html`, this needs an image built from this repository.

Put a settings file in a directory of its own and mount it read only — **it is never built into the
image**, and `.dockerignore` excludes it by name, because a key baked into a layer is a key
published to everyone who can pull it.

```bash
docker run --rm -v "$PWD:/work" -v "$PWD/config:/config:ro" public.ecr.aws/v4q7x8t1/anchor:latest \
    auto /app/examples/aws1/07-trust-decay.dw --config /config/appsettings.json --out /work/out
```

`auto` is **autoformalization**: the only artifact you supply is prose. The agent gets a vocabulary
derived mechanically from the policy, a knowledge article on writing a property module, and your
requirement — and it never sees the policy's rule conditions, so what it drafts cannot be a
restatement of the policy. Three different models and four mechanical gates stand between a draft
and a verdict, and a draft that fails any of them is reported rather than retried into acceptance.

Omit `--intent` and it reads the requirement from a `## <policy>.dw` heading in the `intents.md`
beside the policy — which is how the examples are set up.

`hitl` is the same graph with one node added: before anything is checked, the claim is read back to
you in plain English and you say whether that is what you meant; and when a gate turns a draft away
it asks you about the **requirement**, never about TLA+. It needs a real terminal, so add `-it`:

```bash
docker run --rm -it -v "$PWD:/work" -v "$PWD/config:/config:ro" public.ecr.aws/v4q7x8t1/anchor:latest \
    hitl /app/examples/aws2/03-cumulative-cap.dw --config /config/appsettings.json --out /work/out
```

**What to expect from mode 5.** On the five requirements of `examples/aws2`, an unattended sweep
accepted **one**. Every one of the four failures was a well-formed property that said something the
brief did not quite mean — which is the user-intent formalization gap, measured rather than
asserted, and the reason mode 6 exists.

---

## Reading the exit codes

| | |
|---|---|
| 0 | answered, and nothing to report |
| 1 | a `--property` claim is BROKEN, the audit has findings, or (`scan`) the inputs hold something at medium or high severity |
| 2 | no verdict — and the reason is on stderr. `auto` and `hitl` also exit 2 when they refuse flagged input |
| 3 | could not run |
| 4 | (`explain`) a claim cannot fail; it would pass having tested nothing |

A script can branch on those without parsing prose, which is the point of having them.
