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
# Both, by default, as ONE multi-platform image: a Mac pulls arm64 and runs it natively, an x64
# host pulls amd64, and neither needs --platform. The compile stages cross-compile on the build
# host either way; only the foreign platform's runtime stage (apt-get, pip) runs under emulation.
platforms="linux/amd64,linux/arm64"
dry_run=0
skip_smoke=0

usage() {
    cat <<EOF
Build Anchor's container image, and smoke-test it.

Usage: ./build-docker.sh [version] [-r <repository>] [-p <platforms>] [-n] [-s] [-h]

  version
      The tag, e.g. 0.1.1, given as major.minor.patch. The image is tagged with it and
      with latest, and \`anchor version\` inside it reports it. Default: the version in
      Directory.Build.props.

  -r <repository>
      What to tag, e.g. ghcr.io/you/anchor or an ECR repository URI. Default: anchor.
      A repository listed as frozen in this script is refused.

  -p <platforms>
      linux/amd64, linux/arm64, or both comma-separated. Default: both, as one
      multi-platform image, so Apple Silicon runs it natively. A foreign platform
      cross-compiles; only its runtime stage runs under emulation, which is most of the
      wall time. Both at once needs Docker's containerd image store.

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

After the build, it runs \`version\`, \`scan\` and \`check\` inside the image, once per
platform.

Nothing is pushed; the push commands are printed at the end.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -r|-p)
            [ "$#" -ge 2 ] || { echo "Option $1 requires an argument." >&2; exit 2; }
            if [ "$1" = "-r" ]; then repository="$2"; else platforms="$2"; fi
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
# ECR Public repositories are public.ecr.aws/<alias>/<repository>. The alias alone tags an image
# that builds and then cannot be pushed, which is a slow way to find out.
if [[ "$canonical" =~ ^public\.ecr\.aws/[^/]+$ ]]; then
    echo "$repository is an ECR Public registry alias, not a repository. Name the repository too: $repository/anchor, or whatever you called it." >&2
    exit 2
fi

IFS=',' read -r -a platform_list <<< "$platforms"
[ "${#platform_list[@]}" -gt 0 ] || { echo "-p needs at least one platform." >&2; exit 2; }
for p in "${platform_list[@]}"; do
    case "$p" in
        linux/amd64|linux/arm64) ;;
        *) echo "Each platform must be linux/amd64 or linux/arm64; got '$p'." >&2; exit 2 ;;
    esac
done
[ "$(printf '%s\n' "${platform_list[@]}" | sort -u | wc -l)" -eq "${#platform_list[@]}" ] \
    || { echo "-p names a platform twice: $platforms." >&2; exit 2; }

# ---- checks, all before the build context leaves this machine ----------------------------------

command -v docker >/dev/null 2>&1 || die "docker is not on PATH."
docker buildx version >/dev/null 2>&1 || die "docker buildx is not available."
if ! docker info >/dev/null 2>&1; then
    if [ "$dry_run" -eq 1 ]; then
        warn "the Docker daemon is not reachable; carrying on because this is a dry run"
    else
        die "the Docker daemon is not reachable. Is Docker running?"
    fi
elif [ "${#platform_list[@]}" -gt 1 ]; then
    # The classic image store holds one platform per tag, so `--load` of several fails -- after
    # the whole emulated build has run. Find out now instead.
    docker info --format '{{json .DriverStatus}}' | grep -q 'io.containerd.snapshotter' \
        || die "building $platforms as one image needs Docker's containerd image store (Docker Desktop: Settings > General > Use containerd for pulling and storing images). Or build one platform with -p."
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
     --platform "$platforms"
     --load .)

step "building $image for $platforms"
printf '   '; printf ' %q' "${cmd[@]}"; echo
if [ "$dry_run" -eq 1 ]; then
    echo
    step "dry run: every check passed, nothing was built"
    exit 0
fi
"${cmd[@]}"

# An image built for the wrong platform runs anyway under emulation, slowly, so check each one is
# really there rather than trust the flag.
for p in "${platform_list[@]}"; do
    got="$(docker image inspect --platform "$p" -f '{{.Os}}/{{.Architecture}}' "$image")" \
        || die "$image has no $p variant."
    [ "$got" = "$p" ] || die "$image's $p variant is $got."
    step "$image has $got"
done

# ---- smoke test ---------------------------------------------------------------------------------

# Every platform, because each is its own set of binaries: the arm64 .NET publish and the
# cross-linked dogwood are exactly what an amd64-only test would never exercise. The foreign one
# runs under emulation, so its `check` is slow; that is the price of testing what a Mac will run.
for p in "${platform_list[@]}"; do
    [ "$skip_smoke" -eq 0 ] || break
    run=(docker run --rm --platform "$p")

    # The version the tag claims, not merely a version.
    step "smoke ($p): version"
    # 2>&1: the banner is on STDERR, because under `server` stdout carries MCP frames. Reading
    # stdout alone compared an empty string and reported a mismatch that was not there.
    out="$("${run[@]}" "$image" version 2>&1)" || die "version exited $?."
    printf '%s\n' "$out"
    # A string comparison, not a regex: the dots in a version are literal.
    banner="$(printf '%s\n' "$out" | head -n 1)"
    [[ "$banner" == "Anchor $version" || "$banner" == "Anchor $version+"* ]] \
        || die "the image reports a different version than its tag, $version."

    # The scanner and the sample policies are both in the image, and the samples are clean.
    step "smoke ($p): scan"
    "${run[@]}" -w /app "$image" scan examples tests/policies \
        || die "scan flagged the image's own sample policies, or could not run."

    # A real check: translator, TLC on the JVM, and the checker's reading of the answer.
    step "smoke ($p): check"
    out="$("${run[@]}" -w /app "$image" check tests/policies/dead_forbid.dw)" \
        || die "check exited $? on tests/policies/dead_forbid.dw."
    printf '%s\n' "$out"
    printf '%s' "$out" | grep -q 'forbid #2 .*DEAD' \
        || die "check ran but did not find the dead forbid it always finds. The image is broken."
done

echo
step "built $image and $repository:latest for $platforms from ${head:0:12}$dirty. Nothing was pushed."
[ -z "$dirty" ] || warn "this image contains uncommitted changes; commit first if it is going to be published"
# A name with no '/' is local: pushing it would mean Docker Hub's official-images namespace.
if [[ "$repository" == */* ]]; then
    echo "To publish, when you mean to (each push carries every platform above under the one tag):"
    echo "    docker push $image"
    echo "    docker push $repository:latest"
else
    echo "$repository is a local name. To publish, build again with -r naming a repository you own."
fi
