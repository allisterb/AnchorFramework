#!/usr/bin/env bash
#
# Fetch Anchor's native dependencies and build the solution.
#
# The verifiers need three things the package graph cannot supply, because they are native binaries
# rather than NuGet packages:
#
#   * z3        - Dafny shells out to the solver over SMT-LIB2; it does not use the Z3 managed API,
#                 so the Microsoft.Z3 packages are no help. Fetched from dafny-lang/solver-builds,
#                 which is the build Dafny itself tests against, not the upstream Z3Prover release.
#   * tla2tools - the TLA+ tools jar, used two ways: cross-compiled by IKVM for in-process SANY,
#                 and run on a real JVM for TLC.
#   * a JDK     - checked for, never installed. TLC cannot run under IKVM (see TLCProcess).
#
# lib/ is gitignored, so these are per-machine and a fresh clone needs this script before its first
# build. Downloads are verified against the hashes below and skipped when already present.
#
# Run with -h for usage.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib_dir="$repo_root/lib"

# Keep these in step with Anchor.Verifiers.Dafny.csproj ($Z3Version) and
# Anchor.Verifiers.TLAPlus.csproj ($TLAToolsVersion).
z3_version="4.12.1"
tlatools_version="1.7.4"
solver_builds="https://github.com/dafny-lang/solver-builds/releases/download/snapshot-2025-07-02"
minimum_java_version=11

# sha256 of the files as installed, checked on every run so a silently swapped binary is caught.
#
#   tlatools - the jar whose sha1 (bee4a54f3ee3d4afc347c3240ec2d9e93b075104) matches the published
#              checksum for the v1.7.4 release. Verified.
#   z3       - one hash PER PLATFORM: solver-builds ships a different binary for each OS, so a
#              single pin cannot cover them all. Only the platforms recorded below can be verified,
#              and the script declines to install an unverifiable binary rather than trusting it --
#              warning and carrying on, because z3 is Dafny's solver and the policy path has no
#              use for it.
#              solver-builds publishes no checksums of its own, so these pins are ours, not
#              upstream: each is recorded from a clean download confirmed byte-identical to an
#              independently obtained copy. To add a platform, download the asset by hand, satisfy
#              yourself it is what it claims to be, and record its sha256 here.
tlatools_sha256="936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
z3_sha256_windows="53aca6c734e7d012ec07fe626bba1e3921269777133ce58784d26c4552e3fe0b"
z3_sha256_linux="22214e518eed9eec867d18b485e7b2570d09cbf1d94a47c8eec6ec4de0287eff"
z3_sha256_macos=""

configuration="Release"
run_tests=0
skip_dependencies=0
force=0

usage() {
    cat <<EOF
Fetch Anchor's native dependencies and build the solution.

Usage: ./build.sh [-c Release|Debug] [-t] [-s] [-f] [-h]

  -c <cfg>
      Build configuration, Release (default) or Debug. Passed to dotnet build, and to
      dotnet test when -t is given, so both act on the same output. The launchers
      prefer a Release build, so the default is the one they run.

  -t
      Run the test suite after a successful build. The Dafny tests shell out to z3 and
      the TLA+ tests to java, so this is the flag that proves the whole setup works
      rather than merely compiling. Skipped if the build fails.

  -s
      Do not download anything. Dependencies already in lib/ are still hash-checked and
      a mismatch still stops the build: this suppresses fetching, not verification. A
      dependency that is missing becomes a warning rather than a download, and the build
      then fails in whatever way that missing file causes. Use it to build offline.

  -f
      Re-download both dependencies and replace what is in lib/, even when the files are
      present and their hashes match. Use it when a local copy is suspect, or to exercise
      the download path itself.

  -h
      Show this help and exit.

Examples:

  ./build.sh                  fetch whatever is missing, then build Release
  ./build.sh -t               the same, then run the tests
  ./build.sh -c Debug -t      build and test Debug
  ./build.sh -s               build without touching the network
  ./build.sh -f               re-download both dependencies, then build

Fetched into lib/, which is gitignored, so a fresh clone needs this script first:

  z3 $z3_version
      The solver Dafny shells out to, from dafny-lang/solver-builds — the build Dafny
      itself is tested against, not the upstream Z3Prover release.
  tla2tools $tlatools_version
      The TLA+ tools jar, cross-compiled by IKVM for in-process SANY and run on a
      real JVM for TLC.

Both are checked against pinned sha256 hashes on every run, whether just downloaded
or already present.

PREREQUISITE, not installed by this script:

  A JDK, Java $minimum_java_version or later, on JAVA_HOME or PATH. TLC is run out-of-process on a
  real JVM because it cannot run under IKVM, so the build checks for a JVM and
  stops if there is none. Installing one is up to you.
EOF
}

while getopts ":c:tsfh" opt; do
    case "$opt" in
        c)  configuration="$OPTARG" ;;
        t)  run_tests=1 ;;
        s)  skip_dependencies=1 ;;
        f)  force=1 ;;
        h)  usage; exit 0 ;;
        :)  echo "Option -$OPTARG requires an argument." >&2; echo >&2; usage >&2; exit 2 ;;
        \?) echo "Unknown option -$OPTARG." >&2; echo >&2; usage >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))

if [ "$#" -gt 0 ]; then
    echo "Unexpected argument '$1'. This script takes options only." >&2
    echo >&2
    usage >&2
    exit 2
fi

case "$configuration" in
    Debug|Release) ;;
    *) echo "Configuration must be Debug or Release, got '$configuration'." >&2; exit 2 ;;
esac

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }

# Windows here means git bash / MSYS, where the tools are still .exe and Dafny probes for that name.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) platform="windows"; exe_suffix=".exe" ;;
    Darwin)               platform="macos";   exe_suffix=""     ;;
    *)                    platform="linux";   exe_suffix=""     ;;
esac

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1   # macOS
    fi
}

# present_and_matching <path> <expected>
# 0 when the file is there and matches, 1 when absent. A mismatch is fatal: a dependency whose
# contents changed underneath us is exactly what the hashes exist to catch.
present_and_matching() {
    local path="$1" expected="$2" actual
    [ -f "$path" ] || return 1
    actual="$(sha256_of "$path")"
    if [ "$actual" != "$expected" ]; then
        cat >&2 <<EOF
$path is present but its contents are not what this build expects.
  expected sha256 $expected
  actual   sha256 $actual
Delete the file and re-run to fetch a known copy, or re-run with -f.
EOF
        exit 1
    fi
    return 0
}

download() {
    local uri="$1" dest="$2"
    step "Downloading $uri"
    mkdir -p "$(dirname "$dest")"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error --output "$dest" "$uri"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet --output-document="$dest" "$uri"
    else
        echo "Neither curl nor wget is available to fetch $uri." >&2
        exit 1
    fi
}

assert_hash() {
    local path="$1" expected="$2" uri="$3" actual
    actual="$(sha256_of "$path")"
    if [ "$actual" != "$expected" ]; then
        rm -f "$path"
        cat >&2 <<EOF
Checksum mismatch for $uri
  expected sha256 $expected
  actual   sha256 $actual
The download was discarded. Do not use this file until the mismatch is explained.
EOF
        exit 1
    fi
}

install_z3() {
    # Dafny probes for this exact name next to the executing assembly.
    local target="$lib_dir/z3/bin/z3-$z3_version$exe_suffix"

    # Asset names follow the runner images in dafny-lang/dafny's own workflows. Each OS gets a
    # different binary, so each needs its own recorded hash.
    local asset expected
    case "$platform" in
        windows) asset="z3-$z3_version-x64-windows-2022-bin.zip"; expected="$z3_sha256_windows" ;;
        macos)   asset="z3-$z3_version-x64-macos-13-bin.zip";     expected="$z3_sha256_macos"   ;;
        linux)   asset="z3-$z3_version-x64-ubuntu-22.04-bin.zip"; expected="$z3_sha256_linux"   ;;
    esac

    if [ "$force" -eq 0 ] && present_and_matching "$target" "$expected"; then
        step "z3 $z3_version verified"
        return
    fi
    if [ "$skip_dependencies" -eq 1 ]; then
        warn "z3 $z3_version is missing from $target and -s was given; not fetching it"
        return
    fi

    if [ -z "$expected" ]; then
        # NOT FATAL, and that is a judgement about what z3 is FOR. It is the solver Dafny shells
        # out to over SMT-LIB2; nothing on the Dogwood policy path -- the translator, the checker,
        # TLC -- touches it. So an unpinned platform costs the Dafny verifier and not the build,
        # and the one thing that stays non-negotiable is that an UNVERIFIABLE binary is not
        # installed. A present file with a mismatched hash is still fatal, above.
        local pinned=""
        [ -n "$z3_sha256_windows" ] && pinned="windows"
        [ -n "$z3_sha256_linux" ] && pinned="${pinned:+$pinned, }linux"
        [ -n "$z3_sha256_macos" ] && pinned="${pinned:+$pinned, }macos"
        cat >&2 <<EOF
warning: no z3 sha256 is recorded for $platform, so $asset cannot be verified. NOT INSTALLING IT.

The build carries on. What this costs is the Dafny verifier, which shells out to z3; the
Dogwood policy path does not use it, so \`anchor check\`, \`auto\` and \`hitl\` are unaffected.

To install it anyway, download the asset from
  $solver_builds/$asset
satisfy yourself it is what it claims to be, then record the sha256 of the extracted
z3-$z3_version binary as z3_sha256_$platform in this script and in build.ps1.

Pinned today: ${pinned:-none}.
EOF
        return
    fi

    local scratch
    scratch="$(mktemp -d)"
    trap 'rm -rf "$scratch"' RETURN

    download "$solver_builds/$asset" "$scratch/$asset"
    (cd "$scratch" && unzip -q -o "$asset")

    # The archive holds the versioned binary at its root.
    local binary
    binary="$(find "$scratch" -type f -name "z3-$z3_version*" ! -name '*.zip' | head -1)"
    [ -n "$binary" ] || { echo "No z3-$z3_version binary inside $asset." >&2; exit 1; }

    mkdir -p "$(dirname "$target")"
    mv "$binary" "$target"
    chmod +x "$target"
    assert_hash "$target" "$expected" "$solver_builds/$asset"
    step "z3 $z3_version installed at $target"
}

install_tlatools() {
    local target="$lib_dir/tla2tools-$tlatools_version.jar"

    if [ "$force" -eq 0 ] && present_and_matching "$target" "$tlatools_sha256"; then
        step "tla2tools $tlatools_version verified"
        return
    fi
    if [ "$skip_dependencies" -eq 1 ]; then
        warn "tla2tools $tlatools_version is missing from $target and -s was given; not fetching it"
        return
    fi

    local uri="https://github.com/tlaplus/tlaplus/releases/download/v$tlatools_version/tla2tools.jar"
    download "$uri" "$target"
    assert_hash "$target" "$tlatools_sha256" "$uri"
    step "tla2tools $tlatools_version installed at $target"
}

assert_jdk() {
    local java=""
    if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java$exe_suffix" ]; then
        java="$JAVA_HOME/bin/java$exe_suffix"
    elif command -v java >/dev/null 2>&1; then
        java="$(command -v java)"
    else
        echo "No JVM found. TLC runs out-of-process and needs Java $minimum_java_version or later on JAVA_HOME or PATH." >&2
        exit 1
    fi

    # "java -version" writes to stderr, hence the redirect.
    local banner version major
    banner="$("$java" -version 2>&1 || true)"
    version="$(printf '%s' "$banner" | sed -n 's/.*version "\([0-9][0-9.]*\).*/\1/p' | head -1)"
    if [ -z "$version" ]; then
        echo "Warning: could not read the Java version from:" >&2
        printf '%s\n' "$banner" >&2
        return
    fi

    major="${version%%.*}"
    # 1.8.0_x style versions report major 1; the real major is then the second field.
    if [ "$major" = "1" ]; then
        major="$(printf '%s' "$version" | cut -d. -f2)"
    fi

    if [ "$major" -lt "$minimum_java_version" ]; then
        echo "Java $major found at $java, but tla2tools $tlatools_version needs $minimum_java_version or later." >&2
        exit 1
    fi
    step "Java $major at $java"
}

# Verification always runs, even with -s: checking a file that is already there costs nothing and is
# the only thing standing between a swapped binary and the build consuming it. -s suppresses the
# downloads, not the checks.
install_z3
install_tlatools
assert_jdk

step "Building ($configuration)"
build_args=(build "$repo_root/Anchor.sln" -c "$configuration" --nologo)
# Directory.Build.props commits a lock file per project; CI should fail rather than re-resolve.
[ -n "${CI:-}" ] && build_args+=(-p:RestoreLockedMode=true)
dotnet "${build_args[@]}"

if [ "$run_tests" -eq 1 ]; then
    step "Testing"
    dotnet test "$repo_root/Anchor.sln" -c "$configuration" --nologo --no-build
fi

step "Done"
