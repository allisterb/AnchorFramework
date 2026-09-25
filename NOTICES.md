# Notices and third-party disclosures

Anchor itself is licensed under the **Apache License 2.0** — see [`LICENSE`](LICENSE).

This file discloses every piece of code Anchor incorporates, builds against, or distributes that
was not written for it, in satisfaction of the hackathon rule that an entrant *"must disclose any
other pre-existing code"* incorporated into a submission. It also records what was **read** but not
incorporated, because that distinction is the one most easily blurred.

Anchor's own source — everything under `src/`, `specs/`, `tests/`, `docs/`, `deploy/` and the build
and launcher scripts — was written during the submission period. The repository's first commit is
1 September 2026.

---

## 1. Source incorporated into this repository

**`ext/dogwood` — the Dogwood policy language.** A git submodule, and the only third-party source
in the tree.

| | |
|---|---|
| Upstream | [github.com/dogwood-policy/dogwood](https://github.com/dogwood-policy/dogwood) |
| Licence | **Apache 2.0**, © Amazon.com Inc. `LICENSE` and `NOTICE` in that tree |
| Pinned at | `c6237c88099b3f492ecc5fcee42df06a19224b97` |
| Used for | the semantics `specs/policy/TemporalPolicy` models; its regression corpus as a test oracle; and its CLI, built and run as the reference engine |

**The pin was verified rather than assumed.** The snapshot this project scanned and audited arrived
without a commit SHA, so the two were compared blob for blob — git's blob id computed locally for
every file, raw bytes on both sides so no line-ending filter could fake a match. **35,652 tracked
files, every one byte-identical**; nothing in the commit missing from the snapshot; one file present
only in the snapshot (`Cargo.lock`, which we generate). If the pin is ever moved, none of that
carries with it. See [`reference/README.md`](reference/README.md) for the full record.

No file in `ext/dogwood` has been modified. It is built with `--locked` and **no feature flags** —
in particular not `net`, which would register an `http_get` host function for provider scripts and
make policy evaluation non-deterministic.

---

## 2. Binaries fetched at build time

Neither is committed; `build.sh` / `build.ps1` download them into the gitignored `lib/` and check
them against **pinned sha256 hashes on every run**, whether just downloaded or already present.

| | | |
|---|---|---|
| **tla2tools 1.7.4** | the TLA+ tools — SANY and TLC | **MIT**, © 2019 Microsoft Research (`License.txt` in the jar). The jar also bundles material under the **Eclipse Public License 2.0** (`META-INF/LICENSE.txt`). From [tlaplus/tlaplus](https://github.com/tlaplus/tlaplus) |
| **z3 4.12.1** | the SMT solver Dafny shells out to | **MIT**, from the Z3 project. Taken from [dafny-lang/solver-builds](https://github.com/dafny-lang/solver-builds) — the build Dafny is tested against |

z3 is on the Dafny path only. No Dogwood policy verification reaches it, and the container image
described below does not contain it.

---

## 3. Package dependencies

All three ecosystems are pinned and integrity-checked; none floats.

**.NET (NuGet).** Versions are declared centrally in `requirements/dotnet/Packages.props` and a
`packages.lock.json` per project records a `contentHash` NuGet verifies on every restore.

> `CommandLineParser` 2.9.1 · `IKVM` 8.15.0 · `ModelContextProtocol` 1.4.0 ·
> `ModelContextProtocol.AspNetCore` 1.4.0 · `Microsoft.Extensions.Configuration.Json` 10.0.2 ·
> `Microsoft.Extensions.Logging.Abstractions` 10.0.2 · `Serilog.Extensions.Logging` 10.0.0 ·
> `Serilog.Formatting.Compact` 3.0.0 · `Serilog.Sinks.Console` 6.1.1 · `Serilog.Sinks.File` 7.0.0 ·
> `Serilog.Sinks.Map` 2.0.0 · `SerilogTimings` 3.1.0 · `DafnyPipeline` and `DafnyLanguageServer`
> 4.11.0 — and, for tests only, `xunit` 2.9.2, `xunit.runner.visualstudio` 2.8.2,
> `Microsoft.NET.Test.Sdk` 17.12.0, `coverlet.collector` 6.0.2.

Each carries its own licence, as published on nuget.org.

**Python (PyPI).** Four direct dependencies; `requirements/strands/requirements.txt` is compiled
from `requirements.in` with `--generate-hashes` and installed with `--require-hashes
--only-binary=:all:`, so an install either reproduces exactly the reviewed artifacts or fails, and
no source distribution ever runs a `setup.py`.

> **`strands-agents` 1.54.0** — the Amazon Strands Agents SDK, Apache 2.0, © Amazon.com Inc.
> **`cedarpy` 4.8.7** · **`google-genai` 2.23.0** · plus the transitive tree, which is ~48 packages
> and arrives mostly through one edge, `mcp`.

One honest gap: **`cedarpy` publishes no licence, homepage or author in its PyPI metadata.** It is
pinned to the exact version the Strands SDK itself declares (`cedar = ["cedarpy==4.8.7", ...]`), and
it is used only as a differential-test oracle — no runtime path imports it.

**Rust (crates.io).** Dogwood ships no lockfile, so ours lives at
`requirements/dogwood/Cargo.lock` and is copied in before every build. **271 packages, 268 from
crates.io with a checksum each, none from git.** `cargo audit` and an independent OSV query at the
same pinned versions agree: no vulnerabilities, one informational *unmaintained* notice
(RUSTSEC-2026-0249, `smartstring`, reached via `rhai`). The notable ones are `cedar-policy` and
`cedar-policy-core` 4.11 — Dogwood is built on Cedar rather than reimplementing it.

---

## 4. The container image

`deploy/Dockerfile` publishes an image that redistributes third-party binaries, so they are
disclosed here too:

* **Debian bookworm** base (via `python:3.13-slim-bookworm`) with `default-jre-headless` and
  `libicu72` installed — Debian packages under their own licences, the JRE under **GPL-2.0 with the
  Classpath Exception**.
* **CPython 3.13** and the hash-pinned wheels above.
* **`tla2tools.jar`**, as in §2.
* **The `dogwood` binary**, compiled from the pinned submodule in §1.
* **Anchor's own CLI**, published self-contained, Apache 2.0.