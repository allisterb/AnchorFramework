#!/usr/bin/env bash
#
# Build Anchor's container image from deploy/Dockerfile, check the inputs before it builds, and
# smoke-test the result.
#
#   ./build-docker.sh              tags anchor:<Directory.Build.props version> and anchor:latest
#   ./build-docker.sh 0.1.1        tags anchor:0.1.1 and anchor:latest; `anchor version` says 0.1.1
#
# NOTHING IS PUSHED. The script prints the push commands and leaves running them to you: publishing
# is an outward-facing act, and a build script that could also push is one mistyped flag away from
# overwriting an image somebody else is relying on.
#
# Run with -h for usage. build-docker.ps1 is the same script for PowerShell.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The Dogwood commit whose scan, execution-surface review and cargo audit are recorded in the
# reference ledger. The image BUILDS and SHIPS that tree, so a pin that has moved is a tree nobody
# has checked. If you move the pin: re-scan, re-audit, update the ledger, then this.
audited_dogwood="c6237c88099b3f492ecc5fcee42df06a19224b97"

# Repositories that must not receive a new image. allisterb/anchor is the image submitted for
# judging and has to stay as it was submitted until judging ends; remove it from here after that.
frozen_repositories=("allisterb/anchor")

version=""
repository="anchor"
platform=""
dry_run=0
skip_smoke=0

usage() {
    cat <<EOF
Build Anchor's container image, and smoke-test it.

Usage: ./build-docker.sh [version] [-r <repository>] [-p <platform>] [-n] [-s] [-h]

  version
      The tag, e.g. 0.1.1, given as major.minor.patch. The image is tagged with it and
      with latest, and \`anchor version\` inside it reports it. Default: the version in
      Directory.Build.props.

  -r <repository>
      What to tag, e.g. ghcr.io/you/anchor or an ECR repository URI. Default: anchor.
      A repository listed as frozen in this script is refused.

  -p <platform>
      linux/amd64 or linux/arm64. Default: the Docker daemon's own. A foreign platform
      builds by cross-compiling; only the runtime stage runs under emulation.

  -n
      Dry run: run every check, print the build command, build nothing.

  -s
      Skip the smoke test after the build.

  -h
      Show this help and exit.

Before the build context is sent to the daemon, it checks:

  * .dockerignore still excludes **/appsettings.json, which holds a live API key.
    A key baked into a layer is a key published to everyone who can pull the image.
  * ext/dogwood is checked out, unmodified, at the audited commit
    $audited_dogwood.

After the build, it runs \`version\`, \`scan\` and \`check\` inside the image.

Nothing is pushed; the push commands are printed at the end.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -r|-p)
            [ "$#" -ge 2 ] || { echo "Option $1 requires an argument." >&2; exit 2; }
            if [ "$1" = "-r" ]; then repository="$2"; else platform="$2"; fi
            shift 2 ;;
        -n) dry_run=1; shift ;;
        -s) skip_smoke=1; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "Unknown option $1." >&2; echo >&2; usage >&2; exit 2 ;;
        *)
            [ -z "$version" ] || { echo "Unexpected argument '$1': the version is already '$version'." >&2; exit 2; }
            version="$1"; shift ;;
    esac
done

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# Git bash rewrites anything that looks like a POSIX path in a native program's arguments, so
# `-w /app` would reach docker as `-w C:/Program Files/Git/app`. Harmless everywhere else.
export MSYS_NO_PATHCONV=1

cd "$repo_root"

# ---- arguments ----------------------------------------------------------------------------------

props_version="$(sed -n 's:.*<ProjectAssemblyVersion>\(.*\)</ProjectAssemblyVersion>.*:\1:p' Directory.Build.props | head -n 1)"
[ -n "$props_version" ] || die "could not read ProjectAssemblyVersion from Directory.Build.props."
if [ -z "$version" ]; then
    version="$props_version"
else
    # Three numbers, because the same string becomes the assembly version, which is numeric.
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        || { echo "The version must be major.minor.patch, e.g. 0.1.1; got '$version'." >&2; exit 2; }
    [ "$version" = "$props_version" ] \
        || warn "Directory.Build.props says $props_version. The image will report $version; bump the file so a build from source agrees."
fi

# Docker Hub names can be written with or without the registry and in any case; compare the
# canonical form so none of those spellings gets past the list.
canonical="$(printf '%s' "$repository" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's#^(docker\.io|index\.docker\.io|registry-1\.docker\.io)/##')"
for frozen in "${frozen_repositories[@]}"; do
    [ "$canonical" != "$frozen" ] \
        || die "$repository is frozen: it holds the image submitted for judging and must stay as submitted. Tag another repository with -r."
done

case "$platform" in
    ""|linux/amd64|linux/arm64) ;;
    *) echo "The platform must be linux/amd64 or linux/arm64; got '$platform'." >&2; exit 2 ;;
esac

# ---- checks, all before the build context leaves this machine ----------------------------------

command -v docker >/dev/null 2>&1 || die "docker is not on PATH."
docker buildx version >/dev/null 2>&1 || die "docker buildx is not available."
if ! docker info >/dev/null 2>&1; then
    if [ "$dry_run" -eq 1 ]; then
        warn "the Docker daemon is not reachable; carrying on because this is a dry run"
    else
        die "the Docker daemon is not reachable. Is Docker running?"
    fi
fi

# An exact line, not a substring: a commented-out or negated pattern must not pass. CRs are
# stripped because a Windows clone may have checked the file out with CRLF.
tr -d '\r' < .dockerignore | grep -qxF '**/appsettings.json' \
    || die ".dockerignore no longer excludes **/appsettings.json. Restore it before building: the file holds an API key."
step ".dockerignore excludes the settings file"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "not a git checkout, so the Dogwood pin cannot be verified. Build from a clone."

# `git submodule status` prefixes the commit with '-' (not checked out), '+' (checked out at a
# different commit than the pin) or 'U' (conflicted). Read from the repo root, never from inside
# the submodule.
status="$(git submodule status -- ext/dogwood)"
flag="${status:0:1}"
commit="$(printf '%s' "${status:1}" | cut -d' ' -f1)"
case "$flag" in
    -) die "ext/dogwood is not checked out. Run this yourself, then try again:
    git submodule update --init ext/dogwood" ;;
    +) die "ext/dogwood is checked out at $commit, not at the commit the repository pins. Run 'git submodule update ext/dogwood', or commit the new pin once it has been audited." ;;
    U) die "ext/dogwood has merge conflicts." ;;
esac
[ "$commit" = "$audited_dogwood" ] \
    || die "ext/dogwood is pinned at $commit, but the audited commit is $audited_dogwood. Re-scan and re-audit the new pin (see reference/README.md), then update audited_dogwood in this script."

# porcelain v2 reports a submodule as S<c><m><u>: commit changed, tracked files modified, untracked
# files present. Untracked is expected -- a local build leaves Cargo.lock and target/ there, and the
# image build overwrites the one and .dockerignore excludes the other.
sub="$(git status --porcelain=v2 -- ext/dogwood | awk '$1 == "1" { print $3 }')"
[ "${sub:2:1}" != "M" ] \
    || die "ext/dogwood has modified tracked files. The image would ship code nobody audited; restore them first."
step "ext/dogwood at the audited commit ${audited_dogwood:0:12}, unmodified"

# Uncommitted and untracked files are in the build context all the same, so say so, and say it in
# the image too: the revision carries -dirty, in the label and in `anchor version`.
head="$(git rev-parse HEAD)"
dirty=""
changed="$(git status --porcelain | wc -l | tr -d ' ')"
if [ "$changed" -gt 0 ]; then
    warn "$changed uncommitted or untracked path(s) will be built in; marking the revision -dirty"
    dirty="-dirty"
fi
revision="$head$dirty"

# ---- build --------------------------------------------------------------------------------------

image="$repository:$version"
cmd=(docker buildx build -f deploy/Dockerfile
     -t "$image" -t "$repository:latest"
     --build-arg "ANCHOR_VERSION=$version"
     --build-arg "ANCHOR_REVISION=$revision"
     --label "org.opencontainers.image.title=Anchor"
     --label "org.opencontainers.image.version=$version"
     --label "org.opencontainers.image.revision=$revision"
     --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
     --load)
[ -z "$platform" ] || cmd+=(--platform "$platform")
cmd+=(.)

step "building $image${platform:+ for $platform}"
printf '   '; printf ' %q' "${cmd[@]}"; echo
if [ "$dry_run" -eq 1 ]; then
    echo
    step "dry run: every check passed, nothing was built"
    exit 0
fi
"${cmd[@]}"

# An image built for the wrong platform runs anyway under emulation, slowly, so check it rather
# than trust the flag.
if [ -n "$platform" ]; then
    got="$(docker image inspect -f '{{.Os}}/{{.Architecture}}' "$image")"
    [ "$got" = "$platform" ] || die "$image is $got, expected $platform."
    step "$image is $got"
fi

# ---- smoke test ---------------------------------------------------------------------------------

if [ "$skip_smoke" -eq 0 ]; then
    run=(docker run --rm)
    [ -z "$platform" ] || run+=(--platform "$platform")

    # The version the tag claims, not merely a version.
    step "smoke: version"
    out="$("${run[@]}" "$image" version)" || die "version exited $?."
    printf '%s\n' "$out"
    # A string comparison, not a regex: the dots in a version are literal.
    banner="$(printf '%s\n' "$out" | head -n 1)"
    [[ "$banner" == "Anchor $version" || "$banner" == "Anchor $version+"* ]] \
        || die "the image reports a different version than its tag, $version."

    # The scanner and the sample policies are both in the image, and the samples are clean.
    step "smoke: scan"
    "${run[@]}" -w /app "$image" scan examples tests/policies \
        || die "scan flagged the image's own sample policies, or could not run."

    # A real check: translator, TLC on the JVM, and the checker's reading of the answer.
    step "smoke: check"
    out="$("${run[@]}" -w /app "$image" check tests/policies/dead_forbid.dw)" \
        || die "check exited $? on tests/policies/dead_forbid.dw."
    printf '%s\n' "$out"
    printf '%s' "$out" | grep -q 'forbid #2 .*DEAD' \
        || die "check ran but did not find the dead forbid it always finds. The image is broken."
fi

echo
step "built $image and $repository:latest from ${head:0:12}$dirty. Nothing was pushed."
[ -z "$dirty" ] || warn "this image contains uncommitted changes; commit first if it is going to be published"
# A name with no '/' is local: pushing it would mean Docker Hub's official-images namespace.
if [[ "$repository" == */* ]]; then
    echo "To publish, when you mean to:"
    echo "    docker push $image"
    echo "    docker push $repository:latest"
else
    echo "$repository is a local name. To publish, build again with -r naming a repository you own."
fi
