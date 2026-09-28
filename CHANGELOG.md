# Changelog

Container images are published to `public.ecr.aws/v4q7x8t1/anchor`, for `linux/amd64` and
`linux/arm64` under each tag.

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
- **Progress as it happens**, as plain log lines on stderr with no spinner, so CI logs read the same.
  An audit says up front how many steps it will run, numbers each (`[3/10] 03-data-freshness.dw`)
  with its result and time, and a check announces each TLC run as it starts. Long searches pass on
  TLC's own `Progress(...)` lines. The CLI used to buffer an audit's output until it had finished,
  so all of it arrived at once after minutes of silence. The MCP server is unchanged.

### Fixed

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
