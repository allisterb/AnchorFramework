<#
.SYNOPSIS
    Fetch Anchor's native dependencies and build the solution.

.DESCRIPTION
    The verifiers need two native binaries the package graph cannot supply, because NuGet does not
    carry them:

      z3 4.12.1
          The solver Dafny shells out to over SMT-LIB2. It does not use the Z3 managed API, so the
          Microsoft.Z3 packages are no help. Fetched from dafny-lang/solver-builds, the build Dafny
          itself is tested against, not the upstream Z3Prover release.
      tla2tools 1.7.4
          The TLA+ tools jar, used two ways: cross-compiled by IKVM for in-process SANY, and run on
          a real JVM for TLC.

    lib/ is gitignored, so these are per-machine and a fresh clone needs this script before its
    first build. Both are checked against pinned sha256 hashes on every run, whether just
    downloaded or already present.

    PREREQUISITE, not installed by this script: a JDK, Java 11 or later, on JAVA_HOME or PATH.
    TLC is run out-of-process on a real JVM because it cannot run under IKVM (see TLCProcess),
    so the build checks for a JVM and stops if there is none. Installing one is up to you.

.PARAMETER Configuration
    Build configuration, Release (default) or Debug. Passed to dotnet build, and to dotnet test
    when -Test is given, so both act on the same output. The launchers prefer a Release build, so
    the default is the one they run.

.PARAMETER Test
    Run the test suite after a successful build. The Dafny tests shell out to z3 and the TLA+ tests
    to java, so this is the switch that proves the whole setup works rather than merely compiling.
    Skipped if the build fails.

.PARAMETER SkipDependencies
    Do not download anything. Dependencies already in lib/ are still hash-checked and a mismatch
    still stops the build: this suppresses fetching, not verification. A dependency that is missing
    becomes a warning rather than a download, and the build then fails in whatever way that missing
    file causes. Use it to build offline.

.PARAMETER Force
    Re-download both dependencies and replace what is in lib/, even when the files are present and
    their hashes match. Use it when a local copy is suspect, or to exercise the download path itself.

.PARAMETER Help
    Show this help and exit. Equivalent to -? and to Get-Help on this script.

.EXAMPLE
    ./build.ps1
    Fetch whatever is missing, then build Release.

.EXAMPLE
    ./build.ps1 -Test
    The same, then run the tests.

.EXAMPLE
    ./build.ps1 -Configuration Debug -Test
    Build and test Debug.

.EXAMPLE
    ./build.ps1 -SkipDependencies
    Build without touching the network.

.EXAMPLE
    ./build.ps1 -Force
    Re-download both dependencies, then build.
#>
[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string] $Configuration = 'Release',
    [switch] $Test,
    [switch] $SkipDependencies,
    [switch] $Force,
    # PowerShell's own help switch is -?, which is not what someone arriving from build.sh will
    # reach for. -h binds here by prefix match, since no other parameter starts with an h.
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
$LibDir = Join-Path $RepoRoot 'lib'

# $IsWindows and $IsMacOS are PowerShell 6+ automatic variables; under Windows PowerShell 5.1 they do
# not exist at all, and Set-StrictMode makes reading them an error. Resolve the platform once, here,
# and let the rest of the script use these. The 6+ variables are only touched on 6+.
if ($PSVersionTable.PSVersion.Major -lt 6) {
    $Platform = 'windows'
} elseif ($IsWindows) {
    $Platform = 'windows'
} elseif ($IsMacOS) {
    $Platform = 'macos'
} else {
    $Platform = 'linux'
}
$ExeSuffix = if ($Platform -eq 'windows') { '.exe' } else { '' }

# Keep these in step with Anchor.Verifiers.Dafny.csproj ($Z3Version) and
# Anchor.Verifiers.TLAPlus.csproj ($TLAToolsVersion).
$Z3Version = '4.12.1'
$TLAToolsVersion = '1.7.4'
$SolverBuilds = 'https://github.com/dafny-lang/solver-builds/releases/download/snapshot-2025-07-02'
$MinimumJavaVersion = 11

#region Helpers

function Write-Step([string] $Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Warn([string] $Message) {
    Write-Host "warning: $Message" -ForegroundColor Yellow
}

function Get-FileHashLower([string] $Path) {
    (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# Returns $true when the file is present and matches. An expected hash of $null means "accept
# whatever is there", which is only used for files we cannot pin.
function Test-Dependency([string] $Path, [string] $ExpectedHash) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if (-not $ExpectedHash) { return $true }

    $actual = Get-FileHashLower $Path
    if ($actual -eq $ExpectedHash) { return $true }

    throw @"
$Path is present but its contents are not what this build expects.
  expected sha256 $ExpectedHash
  actual   sha256 $actual
Delete the file and re-run to fetch a known copy, or re-run with -Force.
"@
}

function Save-File([string] $Uri, [string] $Destination) {
    Write-Step "Downloading $Uri"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    # Invoke-WebRequest's progress bar makes large downloads crawl in some hosts.
    $previous = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try { Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing }
    finally { $ProgressPreference = $previous }
}

function Assert-Hash([string] $Path, [string] $ExpectedHash, [string] $Uri) {
    if (-not $ExpectedHash) { return }
    $actual = Get-FileHashLower $Path
    if ($actual -ne $ExpectedHash) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        throw @"
Checksum mismatch for $Uri
  expected sha256 $ExpectedHash
  actual   sha256 $actual
The download was discarded. Do not use this file until the mismatch is explained.
"@
    }
}

#endregion

#region Dependencies

function Install-Z3 {
    # Dafny probes for this exact name next to the executing assembly.
    $exeName = "z3-$Z3Version$ExeSuffix"
    $target = Join-Path $LibDir "z3/bin/$exeName"

    # Asset names follow the runner images in dafny-lang/dafny's own workflows. Each OS gets a
    # different binary, so each needs its own recorded hash.
    $asset = switch ($Platform) {
        'windows' { "z3-$Z3Version-x64-windows-2022-bin.zip" }
        'macos'   { "z3-$Z3Version-x64-macos-13-bin.zip" }
        default   { "z3-$Z3Version-x64-ubuntu-22.04-bin.zip" }
    }
    $expected = $Hashes.Z3[$Platform]

    if (-not $Force -and (Test-Dependency $target $expected)) {
        Write-Step "z3 $Z3Version verified"
        return
    }
    if ($SkipDependencies) {
        Write-Warn "z3 $Z3Version is missing from $target and -SkipDependencies was given; not fetching it"
        return
    }

    if (-not $expected) {
        $pinned = ($Hashes.Z3.GetEnumerator() | Where-Object { $_.Value } | ForEach-Object { $_.Key }) -join ', '
        # NOT FATAL, and that is a judgement about what z3 is FOR. It is the solver Dafny shells
        # out to over SMT-LIB2; nothing on the Dogwood policy path -- the translator, the checker,
        # TLC -- touches it. So an unpinned platform costs the Dafny verifier and not the build,
        # and the one thing that stays non-negotiable is that an UNVERIFIABLE binary is not
        # installed. A present file with a mismatched hash is still fatal, above.
        Write-Warn @"
No z3 sha256 is recorded for $Platform, so $asset cannot be verified. NOT INSTALLING IT.

The build carries on. What this costs is the Dafny verifier, which shells out to z3; the
Dogwood policy path does not use it, so `anchor check`, `auto` and `hitl` are unaffected.

To install it anyway, download the asset from
  $SolverBuilds/$asset
satisfy yourself it is what it claims to be, then record the sha256 of the extracted
z3-$Z3Version binary under Z3.$Platform in this script and as z3_sha256_$Platform in build.sh.

Pinned today: $pinned.
"@
        return
    }

    $scratch = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    try {
        $zip = Join-Path $scratch $asset
        Save-File "$SolverBuilds/$asset" $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $scratch -Force

        # The archive holds the versioned binary at its root.
        $binary = Get-ChildItem -Path $scratch -Filter "z3-$Z3Version*" -File -Recurse |
                  Where-Object { $_.Extension -ne '.zip' } |
                  Select-Object -First 1
        if (-not $binary) { throw "No z3-$Z3Version binary inside $asset." }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Move-Item -LiteralPath $binary.FullName -Destination $target -Force
        Assert-Hash $target $expected "$SolverBuilds/$asset"
        Write-Step "z3 $Z3Version installed at $target"
    }
    finally {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Install-TLATools {
    $target = Join-Path $LibDir "tla2tools-$TLAToolsVersion.jar"

    if (-not $Force -and (Test-Dependency $target $Hashes.TLATools)) {
        Write-Step "tla2tools $TLAToolsVersion verified"
        return
    }
    if ($SkipDependencies) {
        Write-Warn "tla2tools $TLAToolsVersion is missing from $target and -SkipDependencies was given; not fetching it"
        return
    }

    $uri = "https://github.com/tlaplus/tlaplus/releases/download/v$TLAToolsVersion/tla2tools.jar"
    Save-File $uri $target
    Assert-Hash $target $Hashes.TLATools $uri
    Write-Step "tla2tools $TLAToolsVersion installed at $target"
}

function Assert-Jdk {
    $java = $null
    if ($env:JAVA_HOME) {
        $candidate = Join-Path $env:JAVA_HOME "bin/java$ExeSuffix"
        if (Test-Path -LiteralPath $candidate) { $java = $candidate }
    }
    if (-not $java) {
        $command = Get-Command java -CommandType Application -ErrorAction SilentlyContinue |
                   Select-Object -First 1
        if ($command) { $java = $command.Source }
    }

    if (-not $java) {
        throw "No JVM found. TLC runs out-of-process and needs Java $MinimumJavaVersion or later on JAVA_HOME or PATH."
    }

    # "java -version" writes to stderr. Reading it with a PowerShell 2>&1 redirect wraps each line in
    # an ErrorRecord and, under $ErrorActionPreference = 'Stop', fails the script on a successful
    # run. Read the streams directly instead.
    $info = [Diagnostics.ProcessStartInfo]::new($java, '-version')
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    $banner = $process.StandardError.ReadToEnd() + $process.StandardOutput.ReadToEnd()
    $process.WaitForExit()

    if ($banner -notmatch 'version "(?<major>\d+)(\.(?<minor>\d+))?') {
        Write-Warning "Could not read the Java version from:`n$banner`nContinuing."
        return
    }
    # 1.8.0_x style versions report major 1; the real major is then the minor field.
    $major = [int] $Matches['major']
    if ($major -eq 1 -and $Matches['minor']) { $major = [int] $Matches['minor'] }

    if ($major -lt $MinimumJavaVersion) {
        throw "Java $major found at $java, but tla2tools $TLAToolsVersion needs $MinimumJavaVersion or later."
    }
    Write-Step "Java $major at $java"
}

#endregion

# sha256 of the files as installed, checked on every run so a silently swapped binary is caught.
#
#   TLATools - the jar whose sha1 (bee4a54f3ee3d4afc347c3240ec2d9e93b075104) matches the published
#              checksum for the v1.7.4 release. Verified.
#   Z3       - one hash PER PLATFORM: solver-builds ships a different binary for each OS, so a
#              single pin cannot cover them all. Only the platforms recorded below can be verified,
#              and the script declines to install an unverifiable binary rather than trusting it --
#              warning and carrying on, because z3 is Dafny's solver and the policy path has no
#              use for it.
#              solver-builds publishes no checksums of its own, so these pins are ours, not
#              upstream: each is recorded from a clean download confirmed byte-identical to an
#              independently obtained copy. To add a platform, download the asset by hand, satisfy
#              yourself it is what it claims to be, and record its sha256 here.
$Hashes = @{
    TLATools = '936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88'
    Z3       = @{
        windows = '53aca6c734e7d012ec07fe626bba1e3921269777133ce58784d26c4552e3fe0b'
        linux   = '22214e518eed9eec867d18b485e7b2570d09cbf1d94a47c8eec6ec4de0287eff'
        macos   = ''
    }
}

# Verification always runs, even with -SkipDependencies: checking a file that is already there costs
# nothing and is the only thing standing between a swapped binary and the build consuming it.
# -SkipDependencies suppresses the downloads, not the checks.
Install-Z3
Install-TLATools
Assert-Jdk

Write-Step "Building ($Configuration)"
$build = @('build', (Join-Path $RepoRoot 'Anchor.sln'), '-c', $Configuration, '--nologo')
# Directory.Build.props commits a lock file per project; CI should fail rather than re-resolve.
if ($env:CI) { $build += '-p:RestoreLockedMode=true' }
& dotnet @build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Test) {
    Write-Step 'Testing'
    & dotnet test (Join-Path $RepoRoot 'Anchor.sln') -c $Configuration --nologo --no-build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Step 'Done'
