# Changelog

Container images are published to `public.ecr.aws/v4q7x8t1/anchor`, for `linux/amd64` and
`linux/arm64` under each tag.

## Unreleased

### Fixed

**An aggregate written `exists (n: Long). (count …) == n && n > 3` is no longer refused.** Anchor
accepted the `exists` idiom only with its body in parentheses, `exists (n: Long). ((count …) == n
&& n > 3)`, which is how Dogwood's corpus writes it. AWS's AgentCore guide writes every aggregate
without them. That is equally legal Dogwood, since an `exists` scope runs to the right, and
`dogwood check-parse` accepts it. So every rate limit, budget cap and threshold copied from the
guide was refused as outside the modelled subset. Both forms now mean the same thing. Dogwood's
corpus differential is unchanged at 923 pairs.

### Added

`tests/policies/agentcore/`: the 28 worked temporal examples from the AgentCore Developer Guide,
verbatim, with AWS's decision tables as expected decisions, checked by
`tests/strands/agentcore_conformance.py`. See `docs/agentcore.md`.

## 0.1.3

### Changed — breaking

Two options are renamed, because in Anchor "model" means the TLA+ model TLC checks, and an option
about the language model should not read as one about model checking. The old names are gone, not
aliased; a command using them now stops with `Option '...' is unknown`.

| before | now | where |
|---|---|---|
| `--no-model` | `--no-llm` | `anchor check --full`, `src/agent/audit.py` |
| `--model <id>` | `--llm <id>` | `anchor check --full`, `audit.py`, `pipeline.py`, `hitl.py`, `policy_agent.py` |

`--provider` is unchanged. Help text that said "model" for the language model now says "LLM".

**An audit is `check --full`, for a directory or a single policy set.** `check <directory>` used to
audit, writing a report and asking an LLM, while `check <policy-set.dw>` could do neither, so a
single policy set had no way to be audited. Now one flag means one thing whichever the shape:

| command | does |
|---|---|
| `check <policy-set.dw>` | rule-by-rule verdicts, printed; writes nothing, asks no LLM; lists the property modules and questions `--full` would use |
| `check <directory>` | the same, for every `.dw` in it |
| `check <policy-set.dw \| directory> --full` | the audit: property modules paired by header, questions asked of an LLM (`--no-llm` skips them), the report written |

A single policy set's report goes into `<policy-set>-findings/` beside it, so it never overwrites the
directory's. For a single policy set, `--full --property FILE.tla` checks that module as well as the
ones found by header, and the report marks it as given. **`check <directory>` alone no longer writes anything**: add `--full` to any command
that relied on it. Options that apply in only one mode are refused in the other, where several used
to be silently ignored, among them `--event-schema` for a directory, which an audit now takes.

**The default event-schema reading is now Dogwood's own: `callerPrincipal` pinned.** With no
`--event-schema`, a temporal condition sees only the requesting principal's earlier events, which is
what a policy set deployed without a schema of its own gets. It used to be the opposite, unpinned —
every principal's events — so an unconfigured check answered about a deployment nobody gets unless
they ask for it. On every committed example the verdicts are identical under both readings, because
those sessions have one principal, but a policy about several principals ("100 trades an hour
across all agents") is now checked in its per-principal meaning. Pass `--unpinned` for a deployment
whose schema has no universal pin. The reading is stated in every run, as before.

### Added

- **`--pinned` and `--unpinned` on `anchor check`**, for a single policy set and for a directory
  audit, and as `pinned` on the MCP `CheckPolicy` tool. `--pinned` was recommended by the checker's
  own warning and rejected by the CLI as an unknown option. Only one of `--event-schema`, `--pinned`
  and `--unpinned` may be given: the checker used to take the first and ignore the rest, silently.
- **The audit report states its reading**, in an "event-schema reading" row, every run.
- **Every check says what it is about to do before it starts**, on stderr: what is checked and how
  exhaustively, the reading, the property modules and questions, the LLM and where its credentials
  come from, and where the report goes. Anything that can be known to be wrong is said there too,
  before the first TLC run.
- **An audit's LLM is optional unless asked for.** With none of `--llm`, `--provider` or `--config`,
  an LLM that cannot be reached is a warning: the questions are skipped, the checks all run, and the
  report's "questions answered" row says why (`0 of 5 — not asked: no LLM is configured`). Naming
  any of the three makes it a requirement, **proven before the run by a one-token test request**
  through the same client the questions use: a bad key, an unknown model id, a model the account
  may not call or one that cannot take tools stops the run before the first TLC run, exit 3,
  explained where the failure is a known one. A test with no answer within 90 seconds counts as a
  failure, since the Gemini SDK sets no timeout and retries rate limits for minutes. A question that still fails at the call writes the
  report and exits 3. Without any of the three nothing is spent on the test, and a failure is a
  warning. `--llm` or `--provider` with `--no-llm` is refused. A directory with no property module
  is warned about up front.
- **`auto` says what it is doing, as it does it.** It printed nothing between the command and its
  closing summary. It now says up front what it will run (the requirement and where it came
  from, the stages, the LLM and where its model and credentials came from, the reading, where
  the output goes), then a line as each stage starts and ends, and each TLC run in between,
  mutants included. Plain lines only, so a CI log reads the same. A sweep marks each requirement
  with `==== [k/N]` instead of a line redrawn with `\r`. The LLM's configuration is checked
  before the first stage, since drafting cannot happen without one: missing, it stops the run
  with exit 3. **`hitl` gives the same summary** once the requirement is known, and checks the
  LLM before asking the person anything, so nobody types a requirement for a run that cannot
  start. In both, `--config`, `--provider` and `--llm` now lead the help.
- **`Gemini:Model` and `Bedrock:Model` settings**, naming the model each provider runs when `--llm`
  names none, in every mode. The order is `--llm`, then the setting, then the provider's default,
  and an audit's summary says which it used. `--full --provider auto` therefore means "use the LLM
  I have configured, and stop before the run if it cannot be reached".
- **`--config` on `check --full`**, naming the settings file that holds the LLM's key, as `auto` and
  `hitl` already did. An audit could only be pointed at one through `ANCHOR_APPSETTINGS`. The help
  for `--provider` and `--llm` now says where credentials come from, and that `--llm` picks a model
  rather than turning the LLM on: `--full` asks one whenever there is a `questions.md`.
- **Progress as it happens**, as plain log lines on stderr with no spinner, so CI logs read the same.
  An audit says up front how many steps it will run, numbers each (`[3/10] 03-data-freshness.dw`)
  with its result and time, and a check announces each TLC run as it starts. Long searches pass on
  TLC's own `Progress(...)` lines. The CLI used to buffer an audit's output until it had finished,
  so all of it arrived at once after minutes of silence. The MCP server is unchanged.

### Fixed

- **An LLM that could not be built lost the whole audit.** `--provider gemini` with no key, or a
  Bedrock key with no region, raised `SystemExit` from inside the question loop, which caught only
  ordinary exceptions. The audit ended after every check had run and before any was written up,
  exiting 1, which reads as "there are findings". The report is now always written.
- **The MCP server's own logging goes to Anchor's log file**, over stdio and HTTP alike, through
  the provider the CLI configures. Over stdio it was discarded entirely, failed tool calls
  included; over HTTP it went to the host's defaults, which on Windows include the system Event
  Log. A stdio launch stays file-only, so nothing reaches the JSON-RPC stream.
- **A path outside the project is answered as a refusal.** It reached the MCP SDK as an exception,
  which logged it as an unhandled failure with a stack trace; it is now a tool error carrying the
  reason, and one warning line in the log. The message suggested `artifacts/stage1.webp`, a path
  from another project, and now suggests `examples/aws1/agent-policy.dw`.
- **`auto` ends with what it found.** It always model-checked the property it accepted, but said
  so only in findings.md, so it read as needing a `check` afterwards. The run now ends with the
  property's verdict, the rule-by-rule findings and the `check --full --property` command that
  audits the policy set with the new module (findings.md carries the command too). A **BROKEN**
  property is replayed in Dogwood as the session that breaks it, with the engine's verdict and the
  trace kept in `<out>/witness`, as the audit does. `hitl` ends with the same verdicts in plain
  words. Both now exit 1 for a BROKEN property, as `check` and the audit do; `auto` exited 0. A
  draft a gate turned away, which is checked against nothing, ends with the gate's reason and a
  pointer to `hitl`, rather than only `rejected at review`.
- **`auto` said nothing when its LLM could not be reached.** A model id the provider does not have
  (`gemini-2.7.-flash` in `Gemini:Model`) stopped the run at the first draft, but the stage still
  read `-> draft done`, the run ended at `ran 4/8`, and the reason was only in findings.md. The
  stage now reads `FAILED` with the provider's own message and what it means, the end of the run
  repeats it, and the exit is 3, not the rejected-draft 1 -- in `auto`, a sweep and `hitl` alike.
  The explanation names both places a model id can come from, `--llm` and the `Model` setting.
- **A settings file that is not valid JSON says where**, once: `it is not valid JSON: Illegal
  trailing comma before end of object at line 9, column 25. None of its settings apply.` It used to
  say only `JSONDecodeError`, once per setting looked up (five times for one Gemini run), and the
  missing-key error that followed called it "the settings file read". The message quotes nothing
  from the file, which holds keys.
- **A missing `ANCHOR_APPSETTINGS` file is named, not misreported.** When it names a file that is not
  there, no settings file is read. It never falls back to `src/agent/` or the repo root, whatever
  `src/agent/README.md` said, so a different file's key cannot be used by accident. Every LLM mode
  now warns about it before its first call, once, even when the environment supplies the key: the
  file's `Model`, `Region` and `Google` settings have no variables of their own and would silently
  stop applying. The error for a missing key used to say nothing had been named; it names the path.
- **An option that takes a value, given none, is refused.** The parser dropped it without a word, so
  `--event-schema` alone checked under the default reading, `--llm` alone passed even the refusal
  for use without `--full`, and `--attempts` alone used the default bound.
- **An audit given a path relative to the user's directory looked in Anchor's.** The audit runs from
  the Anchor root (`/app` in the container), and was handed paths as typed, so `check my-policies`
  from `/work` looked for `/app/my-policies`. Paths are now made absolute first.
- **A witness directory keeps exactly one event schema**, the one its verdict was reached under. An
  audit re-run under another reading used to leave the old schema beside the new one, and a later
  `anchor timeline` could replay under the wrong one.
- **Witness confirmation now uses the model's reading.** `dogwood replay` was given no event schema
  whenever the caller had none, so the engine fell back to its own pinned default while the model
  was unpinned. It is now always handed the reading as a file, `pinned.dwschema` or
  `unpinned.dwschema`, copied from Dogwood's shipped schemas; a test fails if a copy drifts.
  `anchor timeline` now replays under the schema kept beside a witness, too.
- **Text crosses every subprocess boundary as UTF-8.** On Windows, dogwood's diagnostics came back
  as mojibake, and relayed through the checker could be lost entirely; a non-ASCII string in a TLA+
  module was read and printed back as cp1252. Linux, CI and the container were unaffected.

### Changed

- **`auto` and `hitl` describe every option**, among them `--out`, `--mutants` and
  `--event-schema`, which had no help. The options the two share are defined once, so their help
  cannot drift apart again, and `--provider` rejects an unknown name when the command is read
  rather than when the first model is built.
- **`auto` and `hitl` keep a transcript of every LLM call**, in `transcript.md` beside the run's
  findings.md (for `hitl`, in each `attempt-<n>/`): the drafter with every tool call and its full
  reply, the reviewer and the reporter, each with what it was asked, its model, tokens and time,
  and a note when it failed or was cut off by a cap. Started afresh each run. Only the audit's
  questions had one before; the prose these modes return is a claim, and the transcript is the
  evidence to check it against. findings.md and the opening summary say where it is.
- **The opening summary fits the terminal.** Its values wrap in their own column at 88, as the
  reading does, and paths under the working directory are shown relative to it; a long
  requirement or settings path used to be wrapped again by `hitl`'s 92-column terminal under the
  wrong indent. A line that cannot fit -- one long path -- is now left as laid out rather than
  re-wrapped, which only moved the path without shortening anything. And a stage's progress line is no longer wrapped at
  all: wrapping turned its `\r` into a space, so the elapsed time landed after the description
  instead of replacing it.
- **The reading of a property module is laid out to be read**, wherever it appears: `anchor
  explain`, `hitl`'s checkpoint, findings.md. Labels end in a colon with the value in a column of
  its own, `says:` breaks at its `then` and `forbids:` at its `and yet`, and the states are ONE TO A
  LINE -- a state is itself a comma-separated list, so several on a line could not be told apart.
  It is drawn 88 wide, inside `hitl`'s 92-column terminal: it used to be 96, and the terminal
  wrapped every longer line a second time, splitting a state across the label column.
- **"Property module" for the `.tla` file, "claim" for one invariant in it**, in the checker's
  messages, `auto`'s and `hitl`'s output and reports, and the CLI help, which said "property" for
  both. A verdict is about the module (it holds when every claim in it does); "a claim nobody listed
  is a claim nobody checked" is about one. `--property` keeps its name. Reports already committed
  under `examples/` are records of earlier runs and keep the wording they were written with.
- **"Policy set" for the `.dw` file** throughout the CLI help, the audit report and the checker's
  messages, which said "policy" for it. Dogwood's own term; a policy is one `permit` or `forbid`.

## 0.1.2

### Fixed

- **A directory audit run in the container reported broken claims without the session that breaks
  them.** `checker/witness.py` kept its own path to the `dogwood` binary and ignored
  `ANCHOR_DOGWOOD`, which is how the image says where the binary is, so the engine was never found.
  A missing binary should cost only the engine's confirmation; instead, writing the witness README
  into a directory that had not been created raised, and the whole witness was lost. Both are
  fixed: `findings.md` names the session and the engine's verdict again, and `findings.html` draws
  it. Every earlier image is affected.

## 0.1.1

### Added

- **The input scan.** `anchor scan`, and a scan of every input before a directory audit or an agent
  mode reads it: hidden and reordering characters, look-alike letters, instructions aimed at an LLM,
  markup, terminal escapes, encoded payloads. A high-severity finding stops the LLM from reading the
  input unless `--allow-flagged-input` is given; the checks themselves always run.
- **`findings.html`**, written beside `findings.md` by a directory audit and by `anchor timeline`:
  each broken claim drawn as the session that breaks it. A single self-contained file, with a
  Content-Security-Policy that allows only its own inlined renderer.
- **Images on Amazon ECR Public, for amd64 and arm64**, so Apple Silicon runs them natively.

No longer published: removed from the registry once 0.1.2 replaced it.

## 0.1.0

The version submitted to the Amazon Agents for Humans Hackathon, published as
`allisterb/anchor:0.1.0` on Docker Hub and kept unchanged there while judging runs. amd64 only.
