# syntax=docker/dockerfile:1
#
# Anchor as a command. Pull it and run `anchor` with nothing installed on the host.
#
#   ./build-docker.sh [version]     checks, builds, tags <version> and latest, smoke-tests
#   docker buildx build -f deploy/Dockerfile -t anchor:latest --load .     the same build by hand
#   docker run --rm -v "$PWD:/work" anchor check tests/policies/firewall.dw
#   docker run --rm -v "$PWD:/work" -v "$HOME/.anchor:/config:ro" \
#       anchor auto policy.dw --config /config/appsettings.json --intent "..."
#
# THE SETTINGS FILE IS NEVER BUILT IN. .dockerignore excludes **/appsettings.json by name -- a
# key baked into a layer is a key published to everyone who can pull the image -- so the model
# configuration arrives as a read-only mount named by --config, or as ANCHOR_APPSETTINGS, or as
# a single -e GEMINI_API_KEY where a key is all that is needed.
#
# NOT deploy/Dockerfile.agentcore, which is the Bedrock AgentCore image. That one is a SERVICE: it answers
# POST /invocations on 8080 and its entry point is src/agent/server.py. This one is a COMMAND --
# the entry point is the launcher, so every verb works and arguments are the container's arguments.
# The two are deliberately separate rather than one image with two entry points, because a CLI
# image wants a small surface and a service image wants a fixed one.
#
# FOUR RUNTIMES, which is the whole reason to want this image:
#
#   .NET      the CLI itself. Published SELF-CONTAINED, so no runtime is installed
#   a JVM     TLC is the model checker and it is a real JVM -- IKVM cannot run it in-process
#   CPython   the translator, the checker, and the `auto` / `hitl` drafting modes
#   Rust      not a runtime here but a build input: `dogwood`, the reference engine, is a Rust
#             binary, and src/checker/engine.py shells out to it to say whether a policy the
#             checker refused is outside our subset or simply broken, and to replay a
#             counterexample against the real engine
#
# WHAT IS NOT HERE: Dafny and z3. Neither is on the Dogwood policy path -- no verb reaches the
# solver -- so that is ~90 MB and a per-platform hash pin not spent.
#
# BOTH ARCHITECTURES. The two COMPILE stages run on the BUILD host and cross-compile: dotnet
# publishes per RID, and cargo builds per target with the matching cross linker. So neither an
# emulated .NET nor an emulated Rust build ever happens -- the latter was measured as the
# slowest and least predictable part of the AgentCore image and is why that one carries no Rust.
#
# The RUNTIME stage is deliberately NOT pinned to BUILDPLATFORM, because its layers are the
# target's: an arm64 build on an x64 host runs its apt-get and its pip install under QEMU, and
# that is most of the wall time. Nothing is compiled there, so it is slow rather than fragile.

ARG TLATOOLS_VERSION=1.7.4
ARG TLATOOLS_SHA256=936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88

# ---- stage 1: the .NET CLI, and the jar ---------------------------------------------------------
#
# BUILDPLATFORM, not TARGETPLATFORM: the SDK runs natively and cross-compiles. `RuntimeIdentifiers`
# in Directory.Build.props is what makes this restorable in locked mode, because IKVM and
# System.Data.Odbc resolve per-RID and the lock files carry a section for each.
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:10.0 AS cli
ARG TARGETARCH
ARG TLATOOLS_VERSION
ARG TLATOOLS_SHA256
# What `anchor version` prints, so it agrees with the tag build-docker gives the image. Both are
# optional: unset, the version is Directory.Build.props' and the revision is absent, because .git
# is not in the build context for the SDK to read it from.
ARG ANCHOR_VERSION=
ARG ANCHOR_REVISION=

WORKDIR /src
COPY . .

# Locked restore, as everywhere else: the image must not silently re-resolve a dependency graph.
# A drift fails the build with NU1004 rather than shipping something nobody reviewed.
ENV CI=true

RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) rid=linux-x64   ;; \
        arm64) rid=linux-arm64 ;; \
        *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    dotnet publish src/Anchor.CLI/Anchor.CLI.csproj \
        -c Release -r "$rid" --self-contained true \
        ${ANCHOR_VERSION:+"-p:ProjectAssemblyVersion=$ANCHOR_VERSION"} \
        ${ANCHOR_REVISION:+"-p:SourceRevisionId=$ANCHOR_REVISION"} \
        -o /out/cli

# The jar is not in the repository -- lib/ is gitignored and the build scripts download it. Fetched
# here with the same digest so the image build is self-contained. SOURCE OF TRUTH: build.sh, where
# `tlatools_version` and `tlatools_sha256` live. If you bump one, bump all three.
RUN set -eux; \
    curl -fsSL -o /out/tla2tools.jar \
        "https://github.com/tlaplus/tlaplus/releases/download/v${TLATOOLS_VERSION}/tla2tools.jar"; \
    echo "${TLATOOLS_SHA256}  /out/tla2tools.jar" | sha256sum -c -

# ---- stage 2: dogwood, the reference engine -----------------------------------------------------
#
# Also on the build host, cross-linked rather than emulated. `ext/dogwood` is a submodule pinned at
# a commit verified byte-for-byte against the snapshot that was scanned and audited; see
# reference/README.md, which is also where the terms and the cargo audit are recorded.
#
# THE RUST VERSION is a floor with headroom rather than a minimum. The LANGUAGE floor is
# 1.85: every Dogwood crate is `edition = "2024"` and rustc refuses that before 1.85. Dogwood
# declares no `rust-version`, so its 271-package graph has no recorded MSRV and 1.85 exactly is
# untested -- 1.90 is what this image is built and tested with, which is the version that
# matters for reproducing it.
FROM --platform=$BUILDPLATFORM rust:1.90-slim-bookworm AS dogwood
ARG TARGETARCH

WORKDIR /src
COPY ext/dogwood ext/dogwood
# --locked reads the lockfile from the manifest directory and upstream ships NONE, which is why
# `cargo install --git --locked` was never an option: it would have had nothing to lock against and
# would have re-resolved from crates.io. Ours is at requirements/dogwood/Cargo.lock and is copied
# in, exactly as a local build does it.
COPY requirements/dogwood/Cargo.lock ext/dogwood/Cargo.lock

RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) target=x86_64-unknown-linux-gnu; \
               cross_pkgs="gcc-x86-64-linux-gnu libc6-dev-amd64-cross"; \
               linker_var=CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER; \
               linker=x86_64-linux-gnu-gcc ;; \
        arm64) target=aarch64-unknown-linux-gnu; \
               cross_pkgs="gcc-aarch64-linux-gnu libc6-dev-arm64-cross"; \
               linker_var=CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER; \
               linker=aarch64-linux-gnu-gcc ;; \
        *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    if [ "$target" != "$(rustc -vV | sed -n 's/^host: //p')" ]; then \
        apt-get update; \
        # UNQUOTED, so the two package names split into two arguments. And libc6-dev-*-cross is
        # not optional: gcc-<target> pulls it only as a RECOMMENDS, which --no-install-recommends
        # drops. Without it every crate compiles and the FINAL LINK fails, six minutes in, with
        # `cannot find Scrt1.o` and `cannot find crti.o` -- the C runtime startup objects.
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $cross_pkgs; \
        rm -rf /var/lib/apt/lists/*; \
        rustup target add "$target"; \
        export "$linker_var=$linker"; \
    fi; \
    # NO --features AND NO --all-features, and that is load-bearing rather than tidy. Dogwood can
    # optionally register an `http_get` host function for provider scripts, which makes policy
    # evaluation non-deterministic and network-dependent; the workspace declares no default
    # features and dogwood-cli depends on the language crate plainly, so a build with no feature
    # flags cannot pull it in. Adding one here would silently widen what a verdict means.
    cargo build --release --locked --target "$target" \
        --manifest-path ext/dogwood/Cargo.toml --bin dogwood; \
    mkdir -p /out; \
    install -m 0755 "ext/dogwood/target/$target/release/dogwood" /out/dogwood

# ---- stage 3: the image that runs ---------------------------------------------------------------
#
# Python 3.13 to match the interpreter requirements.txt was compiled against: the lock is hash-
# pinned per wheel, and a different minor version wants different wheels than the recorded digests
# cover.
FROM python:3.13-slim-bookworm AS runtime
ARG TLATOOLS_VERSION

# A headless JRE for TLC -- it needs no display, fonts or browser -- and ICU for .NET.
#
# libicu is not optional and not obvious: a slim Python image has no ICU, and a self-contained .NET
# binary then dies at startup with "Couldn't find a valid ICU package installed on the system". The
# alternative is InvariantGlobalization, which is smaller and WRONG for us: it silently changes
# culture-sensitive string behaviour, so the container would differ from every developer machine in
# ways nothing reports. Pay the ~30 MB and keep the two the same.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        default-jre-headless \
        libicu72; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The same two flags requirements/strands/install.sh passes, for the same two reasons:
#   --require-hashes   every package, transitive ones included, matches its recorded digest
#   --only-binary      no source distribution runs its setup.py during the build
COPY requirements/strands/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The publish OUTPUT DIRECTORY, not a file: a self-contained publish emits hundreds and the
# executable is one of them.
COPY --from=cli     /out/cli           /app/cli
COPY --from=cli     /out/tla2tools.jar /app/lib/tla2tools-${TLATOOLS_VERSION}.jar
COPY --from=dogwood /out/dogwood       /app/bin/dogwood

# The launcher is the entry point, so it is copied rather than reimplemented as a shell line here:
# the verb routing lives in one place and the container behaves like the checkout.
COPY anchor                      /app/anchor
COPY src/translator              /app/src/translator
COPY src/checker                 /app/src/checker
COPY src/agent                   /app/src/agent
# NOT optional, and the omission is silent until a verb runs: pipeline.py does
# `from annotations import VERDICT_PASS, verdict` at import, so without this `auto` and
# `hitl` die with ModuleNotFoundError while `check` works perfectly. It is also what
# translator/strands_graph_to_tla.py imports.
COPY src/annotations             /app/src/annotations
# specs/policy/TemporalPolicy holds Vacuity.tla and DogwoodSemantics.tla, which the checker copies
# into each scratch directory beside the generated PolicyUnderTest.tla. Nothing reaches it by name;
# it is read on every run.
COPY specs/policy/TemporalPolicy /app/specs/policy/TemporalPolicy
# Sample policies, and the ONLY thing here the runtime path does not read. They are what makes the
# image runnable with no mount at all -- `docker run --rm -w /app anchor check
# tests/policies/firewall.dw` answers without a checkout on the host, which is the first thing
# somebody who just pulled it will try.
COPY tests/policies              /app/tests/policies
# The aws1 and aws2 worked examples: the policies, the hand-written property modules and the
# intents.md briefs. 2.3 MB against a 370 MB image, and it is the difference between somebody
# evaluating this image and somebody having to clone a repository first.
COPY examples                    /app/examples

# ANCHOR_ROOT is how the Python half and PythonProcess find the tree when there is no Anchor.sln to
# walk up to, which is exactly the case in an image. The other three name things whose in-checkout
# locations do not exist here: a build output directory, a venv, and a cargo target directory.
ENV ANCHOR_ROOT=/app \
    ANCHOR_CLI=/app/cli/Anchor.CLI \
    ANCHOR_PYTHON=/usr/local/bin/python3 \
    ANCHOR_DOGWOOD=/app/bin/dogwood \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

RUN chmod +x /app/anchor /app/cli/Anchor.CLI /app/bin/dogwood

# Not root. The checker spawns java and the agent modes run model-authored requests through it;
# there is no reason for any of that to hold root in the bargain. /work is the mount point and is
# owned by that user, so output written beside a policy lands somewhere writable.
RUN useradd --create-home --uid 10001 anchor \
    && mkdir -p /work \
    && chown -R anchor:anchor /app /work
USER anchor
WORKDIR /work

# A COMMAND, not a service. Arguments after the image name are the verb and its options, so
# `docker run anchor check policy.dw` reads the way the launcher does.
ENTRYPOINT ["/app/anchor"]
CMD ["help"]
