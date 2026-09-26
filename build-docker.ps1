<#
.SYNOPSIS
    Build Anchor's container image, check the inputs before it builds, and smoke-test the result.

.DESCRIPTION
    Builds deploy/Dockerfile and tags it <repository>:<version> and <repository>:latest.

    Before the build context is sent to the daemon, it checks:

      * .dockerignore still excludes **/appsettings.json, which holds a live API key. A key baked
        into a layer is a key published to everyone who can pull the image.
      * ext/dogwood is checked out, unmodified, at the audited commit. The image builds and ships
        that tree, so a pin that has moved is a tree nobody has checked.

    After the build, it runs `version`, `scan` and `check` inside the image.

    NOTHING IS PUSHED. The script prints the push commands and leaves running them to you:
    publishing is an outward-facing act, and a build script that could also push is one mistyped
    flag away from overwriting an image somebody else is relying on.

    build-docker.sh is the same script for bash.

.PARAMETER Version
    The tag, e.g. 0.1.1, given as major.minor.patch. The image is tagged with it and with latest,
    and `anchor version` inside it reports it. Default: the version in Directory.Build.props.

.PARAMETER Repository
    What to tag, e.g. ghcr.io/you/anchor or an ECR repository URI. Default: anchor. A repository
    listed as frozen in this script is refused.

.PARAMETER Platform
    linux/amd64, linux/arm64, or both comma-separated. Default: both, as one multi-platform image,
    so Apple Silicon runs it natively and neither kind of host needs --platform. A foreign platform
    cross-compiles; only its runtime stage runs under emulation, which is most of the wall time.
    Both at once needs Docker's containerd image store.

.PARAMETER DryRun
    Run every check, print the build command, build nothing.

.PARAMETER SkipSmoke
    Skip the smoke test after the build.

.PARAMETER Help
    Show this help and exit.

.EXAMPLE
    ./build-docker.ps1
    Check, build and smoke-test anchor:<Directory.Build.props version> and anchor:latest.

.EXAMPLE
    ./build-docker.ps1 0.1.1 -Repository ghcr.io/you/anchor
    Build ghcr.io/you/anchor:0.1.1 and :latest, ready for `docker push`.

.EXAMPLE
    ./build-docker.ps1 -DryRun
    Run the checks and print the build command.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string] $Version = '',
    [string] $Repository = 'anchor',
    [string] $Platform = 'linux/amd64,linux/arm64',
    [switch] $DryRun,
    [switch] $SkipSmoke,
    # -h binds here by prefix match, since no other parameter starts with an h.
    [Alias('h')]
    [switch] $Help
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Help) {
    Get-Help -Name $PSCommandPath -Detailed
    exit 0
}

$RepoRoot = $PSScriptRoot

# The Dogwood commit whose scan, execution-surface review and cargo audit are recorded in the
# reference ledger. If you move the pin: re-scan, re-audit, update the ledger, then this.
$AuditedDogwood = 'c6237c88099b3f492ecc5fcee42df06a19224b97'

# Repositories that must not receive a new image. allisterb/anchor is the image submitted for
# judging and has to stay as it was submitted until judging ends; remove it from here after that.
$FrozenRepositories = @('allisterb/anchor')

#region Helpers

function Write-Step([string] $Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Warn([string] $Message) { Write-Host "warning: $Message" -ForegroundColor Yellow }
function Stop-Build([string] $Message, [int] $Code = 1) { Write-Host "error: $Message" -ForegroundColor Red; exit $Code }

# Native commands are run with the repository as an explicit argument rather than by changing
# directory, so nothing here ever has a current directory inside ext/.
function Invoke-Git { & git -C $RepoRoot @args }

# Whether a native command succeeds, output discarded. EAP is lowered for the call because Windows
# PowerShell turns redirected native stderr into ErrorRecords, which 'Stop' then makes fatal.
# No param block on purpose: a named parameter would capture a flag meant for the command, as
# 'git -C' once bound to it. And @() around the rest, because splatting a lone STRING passes its
# characters: `docker info` ran as `docker i n f o`, failed, and read as "the daemon is down".
function Test-Native {
    $ErrorActionPreference = 'Continue'
    $command = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    & $command @rest *> $null
    $LASTEXITCODE -eq 0
}

#endregion

#region Arguments

$props = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot 'Directory.Build.props')
if ($props -notmatch '<ProjectAssemblyVersion>([^<]+)</ProjectAssemblyVersion>') {
    Stop-Build 'could not read ProjectAssemblyVersion from Directory.Build.props.'
}
$PropsVersion = $Matches[1].Trim()
if (-not $Version) {
    $Version = $PropsVersion
} else {
    # Three numbers, because the same string becomes the assembly version, which is numeric.
    if ($Version -notmatch '^\d+\.\d+\.\d+$') {
        Stop-Build "the version must be major.minor.patch, e.g. 0.1.1; got '$Version'." 2
    }
    if ($Version -ne $PropsVersion) {
        Write-Warn "Directory.Build.props says $PropsVersion. The image will report $Version; bump the file so a build from source agrees."
    }
}

# Docker Hub names can be written with or without the registry and in any case; compare the
# canonical form so none of those spellings gets past the list.
$canonical = $Repository.ToLowerInvariant() -replace '^(docker\.io|index\.docker\.io|registry-1\.docker\.io)/', ''
if ($FrozenRepositories -contains $canonical) {
    Stop-Build "$Repository is frozen: it holds the image submitted for judging and must stay as submitted. Tag another repository with -Repository."
}
# ECR Public repositories are public.ecr.aws/<alias>/<repository>. The alias alone tags an image
# that builds and then cannot be pushed, which is a slow way to find out.
if ($canonical -match '^public\.ecr\.aws/[^/]+$') {
    Stop-Build "$Repository is an ECR Public registry alias, not a repository. Name the repository too: $Repository/anchor, or whatever you called it." 2
}

$Platforms = @($Platform.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($Platforms.Count -eq 0) { Stop-Build '-Platform needs at least one platform.' 2 }
foreach ($p in $Platforms) {
    if ($p -cnotin 'linux/amd64', 'linux/arm64') { Stop-Build "each platform must be linux/amd64 or linux/arm64; got '$p'." 2 }
}
if (@($Platforms | Select-Object -Unique).Count -ne $Platforms.Count) { Stop-Build "-Platform names a platform twice: $Platform." 2 }
$Platform = $Platforms -join ','

#endregion

#region Checks, all before the build context leaves this machine

if (-not (Get-Command docker -CommandType Application -ErrorAction SilentlyContinue)) {
    Stop-Build 'docker is not on PATH.'
}
if (-not (Test-Native docker buildx version)) { Stop-Build 'docker buildx is not available.' }
if (-not (Test-Native docker info)) {
    if ($DryRun) { Write-Warn 'the Docker daemon is not reachable; carrying on because this is a dry run' }
    else { Stop-Build 'the Docker daemon is not reachable. Is Docker running?' }
} elseif ($Platforms.Count -gt 1) {
    # The classic image store holds one platform per tag, so `--load` of several fails -- after the
    # whole emulated build has run. Find out now instead.
    if ((& docker info --format '{{json .DriverStatus}}' | Out-String) -notmatch 'io\.containerd\.snapshotter') {
        Stop-Build "building $Platform as one image needs Docker's containerd image store (Docker Desktop: Settings > General > Use containerd for pulling and storing images). Or build one platform with -Platform."
    }
}

# An exact line, not a substring: a commented-out or negated pattern must not pass. Trimmed of CR
# because a Windows clone may have checked the file out with CRLF.
$ignored = Get-Content -LiteralPath (Join-Path $RepoRoot '.dockerignore') | ForEach-Object { $_.TrimEnd("`r") }
if ($ignored -cnotcontains '**/appsettings.json') {
    Stop-Build '.dockerignore no longer excludes **/appsettings.json. Restore it before building: the file holds an API key.'
}
Write-Step '.dockerignore excludes the settings file'

if (-not (Test-Native git -C $RepoRoot rev-parse --is-inside-work-tree)) {
    Stop-Build 'not a git checkout, so the Dogwood pin cannot be verified. Build from a clone.'
}

# `git submodule status` prefixes the commit with '-' (not checked out), '+' (checked out at a
# different commit than the pin) or 'U' (conflicted).
$status = (Invoke-Git submodule status -- ext/dogwood | Out-String).TrimEnd()
$flag = $status.Substring(0, 1)
$commit = $status.Substring(1).Split(' ')[0]
switch -CaseSensitive ($flag) {
    '-' { Stop-Build "ext/dogwood is not checked out. Run this yourself, then try again:`n    git submodule update --init ext/dogwood" }
    '+' { Stop-Build "ext/dogwood is checked out at $commit, not at the commit the repository pins. Run 'git submodule update ext/dogwood', or commit the new pin once it has been audited." }
    'U' { Stop-Build 'ext/dogwood has merge conflicts.' }
}
if ($commit -ne $AuditedDogwood) {
    Stop-Build "ext/dogwood is pinned at $commit, but the audited commit is $AuditedDogwood. Re-scan and re-audit the new pin (see reference/README.md), then update `$AuditedDogwood in this script."
}

# porcelain v2 reports a submodule as S<c><m><u>: commit changed, tracked files modified, untracked
# files present. Untracked is expected -- a local build leaves Cargo.lock and target/ there, and the
# image build overwrites the one and .dockerignore excludes the other.
$sub = Invoke-Git status --porcelain=v2 -- ext/dogwood |
       Where-Object { $_ -like '1 *' } | ForEach-Object { $_.Split(' ')[2] }
if ($sub -and $sub.Length -ge 3 -and $sub[2] -ceq 'M') {
    Stop-Build 'ext/dogwood has modified tracked files. The image would ship code nobody audited; restore them first.'
}
Write-Step "ext/dogwood at the audited commit $($AuditedDogwood.Substring(0, 12)), unmodified"

# Uncommitted and untracked files are in the build context all the same, so say so, and say it in
# the image too: the revision carries -dirty, in the label and in `anchor version`.
$Head = (Invoke-Git rev-parse HEAD | Out-String).Trim()
$Dirty = ''
$changed = @(Invoke-Git status --porcelain).Count
if ($changed -gt 0) {
    Write-Warn "$changed uncommitted or untracked path(s) will be built in; marking the revision -dirty"
    $Dirty = '-dirty'
}
$Revision = "$Head$Dirty"

#endregion

#region Build

$Image = "${Repository}:$Version"
$cmd = @('buildx', 'build', '-f', (Join-Path $RepoRoot 'deploy/Dockerfile'),
         '-t', $Image, '-t', "${Repository}:latest",
         '--build-arg', "ANCHOR_VERSION=$Version",
         '--build-arg', "ANCHOR_REVISION=$Revision",
         '--label', 'org.opencontainers.image.title=Anchor',
         '--label', "org.opencontainers.image.version=$Version",
         '--label', "org.opencontainers.image.revision=$Revision",
         '--label', "org.opencontainers.image.created=$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
         '--platform', $Platform,
         '--load', $RepoRoot)

Write-Step "building $Image for $Platform"
Write-Host "    docker $($cmd -join ' ')"
if ($DryRun) {
    Write-Host
    Write-Step 'dry run: every check passed, nothing was built'
    exit 0
}
& docker @cmd
if ($LASTEXITCODE -ne 0) { Stop-Build "docker buildx build exited $LASTEXITCODE." }

# An image built for the wrong platform runs anyway under emulation, slowly, so check each one is
# really there rather than trust the flag.
foreach ($p in $Platforms) {
    $got = (& docker image inspect --platform $p -f '{{.Os}}/{{.Architecture}}' $Image | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Build "$Image has no $p variant." }
    if ($got -ne $p) { Stop-Build "${Image}'s $p variant is $got." }
    Write-Step "$Image has $got"
}

#endregion

#region Smoke test

# Every platform, because each is its own set of binaries: the arm64 .NET publish and the
# cross-linked dogwood are exactly what an amd64-only test would never exercise. The foreign one
# runs under emulation, so its `check` is slow; that is the price of testing what a Mac will run.
foreach ($p in $(if ($SkipSmoke) { @() } else { $Platforms })) {
    $run = @('run', '--rm', '--platform', $p)

    # The version the tag claims, not merely a version.
    Write-Step "smoke (${p}): version"
    # 2>&1: the banner is on STDERR, because under `server` stdout carries MCP frames. Reading
    # stdout alone compared an empty string and reported a mismatch that was not there. EAP is
    # lowered for the call because Windows PowerShell makes redirected native stderr an ErrorRecord,
    # which 'Stop' would turn fatal; each record is turned back into its text.
    $out = & {
        $ErrorActionPreference = 'Continue'
        & docker @run $Image version 2>&1 | ForEach-Object { "$_" } | Out-String
    }
    if ($LASTEXITCODE -ne 0) { Stop-Build "version exited $LASTEXITCODE." }
    Write-Host $out.TrimEnd()
    if ($out -notmatch "(?m)^Anchor $([regex]::Escape($Version))(\+|\s*$)") {
        Stop-Build "the image reports a different version than its tag, $Version."
    }

    # The scanner and the sample policies are both in the image, and the samples are clean.
    Write-Step "smoke (${p}): scan"
    & docker @run -w /app $Image scan examples tests/policies
    if ($LASTEXITCODE -ne 0) { Stop-Build "scan flagged the image's own sample policies, or could not run." }

    # A real check: translator, TLC on the JVM, and the checker's reading of the answer.
    Write-Step "smoke (${p}): check"
    $out = & docker @run -w /app $Image check tests/policies/dead_forbid.dw | Out-String
    $code = $LASTEXITCODE
    Write-Host $out.TrimEnd()
    if ($code -ne 0) { Stop-Build "check exited $code on tests/policies/dead_forbid.dw." }
    if ($out -notmatch 'forbid #2 .*DEAD') {
        Stop-Build 'check ran but did not find the dead forbid it always finds. The image is broken.'
    }
}

#endregion

Write-Host
Write-Step "built $Image and ${Repository}:latest for $Platform from $($Head.Substring(0, 12))$Dirty. Nothing was pushed."
if ($Dirty) { Write-Warn 'this image contains uncommitted changes; commit first if it is going to be published' }
# A name with no '/' is local: pushing it would mean Docker Hub's official-images namespace.
if ($Repository.Contains('/')) {
    Write-Host 'To publish, when you mean to (each push carries every platform above under the one tag):'
    Write-Host "    docker push $Image"
    Write-Host "    docker push ${Repository}:latest"
} else {
    Write-Host "$Repository is a local name. To publish, build again with -Repository naming a repository you own."
}
