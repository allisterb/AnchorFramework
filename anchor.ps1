<#
.SYNOPSIS
    Anchor's entry point. Dispatches the verb to the .NET CLI or to Python.

.DESCRIPTION
    Anchor's verbs do not all live behind the same runtime:

      server, check, explain, help, version    the .NET CLI, src/Anchor.CLI
      auto                                     Python, src/agent/pipeline.py
      hitl                                     Python, src/agent/hitl.py
      timeline                                 Python, src/checker/timeline.py
      scan                                     Python, src/checker/scan.py

    The split is deliberate rather than historical. `check`, `explain` and `server` are genuinely
    C#-fronted -- the checker is reached through them and the MCP server IS them. The two drafting
    modes are argparse programs with a couple of dozen options each, and a CLI verb for either
    would re-declare every one of those options, so each would live in two places and adding one to
    the Python would leave it unreachable from the CLI until somebody remembered. Then it would
    spawn Python anyway. This script is that dispatch without the second copy of the flags and
    without the process hop -- which matters most for `hitl`, whose whole job is to read answers
    from a terminal.

    Arguments are forwarded verbatim and the exit code is passed through, so anything documented
    for `anchor check` or for `python src/agent/hitl.py` works here unchanged.

    Interpreter and binary are found in this order:

      ANCHOR_PYTHON, then the repo venv at python/, then python3 / python on PATH
      ANCHOR_CLI, then a Release build, then a Debug build, under src/Anchor.CLI/bin

    ANCHOR_CLI may name either the managed dll or a self-contained executable; a .dll is run
    through `dotnet` and anything else is run directly. Those are the same two rules
    src/agent/policy_agent.py and the container image already use.

.EXAMPLE
    ./anchor.ps1 check examples/aws2/agent-policy.dw --property Intent.tla
    Mechanically check a policy against a property module you wrote.

.EXAMPLE
    ./anchor.ps1 auto policy.dw --intent "A refund over five hundred needs a supervisor."
    Draft the property module from the brief and check it, unattended.

.EXAMPLE
    ./anchor.ps1 hitl policy.dw
    The same, with you answering when a gate turns a draft away.

.EXAMPLE
    ./anchor.ps1 server --http --port 8080
    The MCP server.
#>

# No param block, deliberately: everything reaching this script belongs to the verb, and a
# parameter declared here would swallow the argument of whichever verb happened to share its name.
# $args is the whole command line, untouched.

# 'Continue', deliberately, and set rather than inherited. Windows PowerShell wraps a native
# command's stderr in an ErrorRecord when the stream is redirected, so under 'Stop' an ordinary
# diagnostic from the CLI becomes a terminating error HERE: `anchor nosuchverb 2>&1` died that way.
# `hitl` would be worse -- its whole conversation goes to stderr so that stdout can carry the report
# path. Nothing below relies on 'Stop': the failures this script raises are `throw`, which
# terminates whatever the preference says.
$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$RepoRoot = $PSScriptRoot

# The routing table, and the only place a new Python verb needs adding.
$PythonVerbs = @{
    auto     = 'src/agent/pipeline.py'
    hitl     = 'src/agent/hitl.py'
    timeline = 'src/checker/timeline.py'
    scan     = 'src/checker/scan.py'
}

# The CLI's own help cannot mention the verbs it does not have, so this script says them after.
$HelpTokens = @('help', '--help', '-h', '-?', '/?')

# $IsWindows is a PowerShell 6+ automatic variable and does not exist at all under Windows
# PowerShell 5.1, where Set-StrictMode makes reading it an error. Resolve the platform once.
if ($PSVersionTable.PSVersion.Major -lt 6) {
    $OnWindows = $true
} else {
    $OnWindows = [bool] $IsWindows
}

function Find-Python {
    # Trusted as given: a caller who set it knows better than this search does.
    if ($env:ANCHOR_PYTHON) { return $env:ANCHOR_PYTHON }

    $candidates = @(Join-Path $RepoRoot 'python/bin/python3'), (Join-Path $RepoRoot 'python/bin/python')
    if ($OnWindows) { $candidates = @(Join-Path $RepoRoot 'python/Scripts/python.exe') }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    # PATH last. On Windows this can find the App Execution Alias under WindowsApps, which exists as
    # a file and only ever prints "Python was not found" -- PythonProcess.Runs rules that one out by
    # executing a line and reading the answer back. Here the failure is at least loud.
    foreach ($name in @('python3', 'python')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
                   Select-Object -First 1
        if ($command) { return $command.Source }
    }

    throw @"
No usable Python found, and the drafting modes are Python.
Create the repo venv (requirements/strands/install.cmd), put python on PATH, or set ANCHOR_PYTHON.
"@
}

function Find-Cli {
    if ($env:ANCHOR_CLI) {
        if ([IO.Path]::GetExtension($env:ANCHOR_CLI) -eq '.dll') {
            return [pscustomobject]@{ Exe = 'dotnet'; Prefix = @($env:ANCHOR_CLI) }
        }
        return [pscustomobject]@{ Exe = $env:ANCHOR_CLI; Prefix = @() }
    }

    $apphost = if ($OnWindows) { 'Anchor.CLI.exe' } else { 'Anchor.CLI' }

    # Release before Debug: a Release tree is the deliberate one. Same order as policy_agent.py.
    foreach ($configuration in @('Release', 'Debug')) {
        $dir = Join-Path $RepoRoot "src/Anchor.CLI/bin/$configuration/net10.0"

        # The apphost when the build produced one, because it needs no dotnet on PATH.
        $exe = Join-Path $dir $apphost
        if (Test-Path -LiteralPath $exe -PathType Leaf) {
            return [pscustomobject]@{ Exe = $exe; Prefix = @() }
        }

        $dll = Join-Path $dir 'Anchor.CLI.dll'
        if (Test-Path -LiteralPath $dll -PathType Leaf) {
            return [pscustomobject]@{ Exe = 'dotnet'; Prefix = @($dll) }
        }
    }

    throw @"
The Anchor CLI is not built. Run:
    ./build.ps1
or set ANCHOR_CLI to the path of Anchor.CLI.dll.
"@
}

function Invoke-Python([string] $Verb, [string] $Script, [string[]] $Rest) {
    if ($null -eq $Rest) { $Rest = @() }
    $python = Find-Python
    # So that argparse opens with "usage: anchor.ps1 hitl" rather than naming a file nobody invoked.
    $env:ANCHOR_VERB = "$(Split-Path -Leaf $PSCommandPath) $Verb"
    $line = @((Join-Path $RepoRoot $Script)) + @($Rest)
    & $python @line
    exit $LASTEXITCODE
}

function Show-ExtraVerbs {
    Write-Output '  auto       Draft the property module from a natural language brief and check it, unattended'
    Write-Output ''
    Write-Output '  hitl       Draft the property module from a natural language brief with a human answering when a gate turns a draft away'
    Write-Output ''
    Write-Output '  timeline   Build the data a timeline visualisation draws, from a witness directory written by a check'
    Write-Output ''
    Write-Output '  scan       Look for hidden text, adversarial prompts and markup in a policy''s inputs before a model sees them'
    Write-Output ''
}

$verb = if ($args.Count -gt 0) { [string] $args[0] } else { '' }

# Assigned first and then replaced, NOT `$rest = if (...) {...} else { @() }`: PowerShell unrolls a
# script block's output and an empty array outputs nothing, so that form leaves $rest null -- and
# $null.Count under Set-StrictMode is an error rather than 0.
$rest = @()
if ($args.Count -gt 1) { $rest = @($args[1..($args.Count - 1)]) }

# `anchor help auto`, which the CLI would reject as a verb name it has never heard of.
if (($HelpTokens -contains $verb) -and $rest.Count -gt 0) {
    $topic = [string] $rest[0]
    if ($PythonVerbs.ContainsKey($topic)) {
        Invoke-Python $topic ($PythonVerbs[$topic]) @('--help')
    }
}

if ($PythonVerbs.ContainsKey($verb)) {
    Invoke-Python $verb ($PythonVerbs[$verb]) $rest
}

# Everything else is the CLI's, including an unknown verb: its parser writes a better error than a
# guess here would, and a verb added to the CLI works through this script without it being touched.
$cli = Find-Cli
$line = @($cli.Prefix) + @($args)
& $cli.Exe @line
$code = $LASTEXITCODE

if ($HelpTokens -contains $verb) { Show-ExtraVerbs }

exit $code
