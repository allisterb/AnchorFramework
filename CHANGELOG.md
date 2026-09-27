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
| `--no-model` | `--no-llm` | `anchor check <directory>`, `src/agent/audit.py` |
| `--model <id>` | `--llm <id>` | `anchor check <directory>`, `audit.py`, `pipeline.py`, `hitl.py`, `policy_agent.py` |

`--provider` is unchanged. Help text that said "model" for the language model now says "LLM".

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
