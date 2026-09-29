namespace Anchor.Tests.MCPServer;

using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

using Anchor.Verifiers.TLAPlus;

/// <summary>
/// <c>anchor check</c>, run as a process, held to its documented exit codes.
/// </summary>
/// <remarks>
/// <para>
/// The exit code is the part a script branches on, and it is the part nothing else tests: every
/// other route into the checker returns a <c>PolicyCheckResult</c>, where "answered" and "a claim
/// is broken" are separate fields that cannot be confused. Through a process they collapse onto one
/// integer, and the CLI is where that mapping could be wrong.
/// </para>
/// <para>
/// The mapping is deliberately the checker's own, so that <c>anchor check</c> and the Python entry
/// point can be swapped in a script:
/// 0 answered, 1 a property is BROKEN, 2 no verdict, 3 the checker could not run at all.
/// </para>
/// </remarks>
public class CliCheckTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// A finding is not an error. A DEAD forbid is the most alarming thing this fixture contains
    /// and it still exits 0, because the run ANSWERED.
    /// </summary>
    [CliPolicyFact]
    public async Task AFindingExitsZeroAndPrintsTheVerdicts()
    {
        var (exit, stdout, _) = await RunAsync("check", "tests/policies/dead_forbid.dw");

        Assert.Equal(0, exit);
        Assert.Contains("permit #1", stdout);
        Assert.Contains("DEAD", stdout);

        // The caveat that makes the verdict honest travels with it.
        Assert.Contains("uses Dogwood's own default", stdout, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// A violated `--property` claim exits 1 — the one outcome that is genuinely an error to a
    /// script, and the most useful answer the checker gives.
    /// </summary>
    [CliPolicyFact]
    public async Task ABrokenPropertyExitsOne()
    {
        var (broken, stdout, _) = await RunAsync(
            "check", "tests/policies/firewall_open.dw", "--property", "tests/policies/firewall.tla");

        Assert.Equal(1, broken);
        Assert.Contains("BROKEN", stdout);
        Assert.Contains("external", stdout);

        // And the same property against the policy it was written for holds, so the 1 above is
        // about the policy rather than about the harness.
        var (held, heldOut, _) = await RunAsync(
            "check", "tests/policies/firewall.dw", "--property", "tests/policies/firewall.tla");

        Assert.Equal(0, held);
        Assert.Contains("every claim holds", heldOut);
    }

    /// <summary>
    /// A refusal exits 2 and says why on stderr — distinct from 0, because no verdict was reached
    /// and "no findings" would be the wrong thing for a script to conclude.
    /// </summary>
    [CliPolicyFact]
    public async Task ARefusalExitsTwoAndExplainsItselfOnStderr()
    {
        var (exit, _, stderr) = await RunAsync("check", "tests/policies/like_impossible.dw");

        Assert.Equal(2, exit);
        Assert.Contains("REFUSED", stderr);
        Assert.Contains("glob intersection", stderr);
    }

    /// <summary>A missing file is also "no verdict", not a crash.</summary>
    [CliPolicyFact]
    public async Task AMissingPolicyExitsTwo()
    {
        var (exit, _, stderr) = await RunAsync("check", "tests/policies/no_such_policy.dw");

        Assert.Equal(2, exit);
        Assert.Contains("no such policy file", stderr);
    }

    /// <summary>
    /// Naming no policy is a usage error, and says so rather than producing a stack trace.
    /// </summary>
    /// <remarks>
    /// The message is System.CommandLine's; the EXIT CODE is ours. The library defaults a parse
    /// error to 1, which here already means "a --property claim is BROKEN", so a script could not
    /// have told "you typed it wrong" from "the policy does not mean what you said it means". That
    /// override is the thing this test is really guarding.
    /// </remarks>
    [CliFact]
    public async Task NamingNoPolicyIsAUsageError()
    {
        var (exit, _, stderr) = await RunAsync("check");

        Assert.Equal(2, exit);
        Assert.Contains("required value not bound to option name is missing", stderr);
    }

    /// <summary>An unknown verb does not silently start the server.</summary>
    [CliFact]
    public async Task AnUnknownVerbIsRefused()
    {
        var (exit, stdout, stderr) = await RunAsync("frobnicate");

        Assert.Equal(2, exit);
        Assert.Contains("Unrecognised command", stderr);
        Assert.Contains("frobnicate", stderr);
        Assert.Empty(stdout);
    }

    /// <summary>
    /// Without --full, a check writes nothing and asks no LLM, and says what an audit would add:
    /// the property modules and questions it did not use. Before --full existed nothing told a
    /// reader that a policy set had stated intentions beside it at all.
    /// </summary>
    [CliPolicyFact]
    public async Task APlainCheckWritesNothingAndListsWhatFullWouldUse()
    {
        var folder = Path.Combine(StdioTransportTests.Repo, "examples", "aws1", "07-trust-decay-findings");
        var (exit, stdout, stderr) = await RunAsync("check", "examples/aws1/07-trust-decay.dw");

        Assert.Equal(0, exit);

        // Each TLC run announced as it starts, on stderr: a policy set with many rules is minutes
        // of TLC, and silence reads as a hang. The verdicts on stdout are untouched by it.
        Assert.Contains("TLC 1/2  permit #1: does deleting it change any verdict?", stderr);
        Assert.Contains("TLC 2/2  permit #1: can it grant anything at all?", stderr);
        Assert.DoesNotContain("TLC 1/2", stdout);

        Assert.Contains("Not checked, and available to --full", stdout);
        Assert.Contains("TrustDecay.tla", stdout);
        Assert.Contains("TrustDecay10.tla", stdout);
        Assert.Contains("uses an LLM", stdout);
        Assert.False(Directory.Exists(folder), "a plain check wrote a report");
    }

    /// <summary>
    /// An option that means something in only one mode is refused in the other, never ignored.
    /// Several used to be dropped silently -- `--event-schema` for a directory among them, which
    /// checked under a reading the caller had not asked for.
    /// </summary>
    [CliFact]
    public async Task OptionsThatDoNotApplyAreRefusedNotIgnored()
    {
        foreach (var (args, why) in new[]
                 {
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--no-llm" },
                      "--no-llm applies only with --full"),
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--allow-flagged-input" },
                      "--allow-flagged-input applies only with --full"),
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--config", "x.json" },
                      "--config applies only with --full"),
                     (new[] { "check", "examples/aws1", "--property", "x.tla" },
                      "--property applies to a single policy set file, not a directory"),
                     (new[] { "check", "examples/aws1", "--full", "--keep", "x" },
                      "--keep applies to a check without --full"),
                     (new[] { "check", "examples/aws1", "--full", "--property", "x.tla" },
                      "--property applies to a single policy set file, not a directory")
                 })
        {
            var (exit, _, stderr) = await RunAsync(args);

            Assert.True(exit == 2, $"{string.Join(' ', args)} exited {exit}: {stderr}");
            Assert.Contains(why, stderr);
        }
    }

    /// <summary>
    /// An option that takes a value, given none, is refused. The parser dropped it silently, so a
    /// bare `--event-schema` checked under the default reading and a bare `--llm` passed every
    /// refusal. None of these has --full, so a regression here reaches no LLM.
    /// </summary>
    [CliFact]
    public async Task AnOptionWithNoValueIsRefusedNotDropped()
    {
        foreach (var (args, name) in new[]
                 {
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--llm" }, "--llm"),
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--event-schema" }, "--event-schema"),
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--attempts", "--verbose" }, "--attempts"),
                     (new[] { "check", "tests/policies/dead_forbid.dw", "--output-dir=" }, "--output-dir")
                 })
        {
            var (exit, _, stderr) = await RunAsync(args);

            Assert.True(exit == 2, $"{string.Join(' ', args)} exited {exit}: {stderr}");
            Assert.Contains($"{name} needs a value", stderr);
        }
    }

    /// <summary>
    /// --full audits a single policy set as it would a directory -- its own modules, found by
    /// header -- and writes the report into a folder of its own, so it cannot overwrite the report
    /// for the directory the policy set sits in.
    /// </summary>
    [CliPolicyFact]
    public async Task FullAuditsASinglePolicySetIntoItsOwnFolder()
    {
        var aws1 = Path.Combine(StdioTransportTests.Repo, "examples", "aws1");
        var work = Directory.CreateTempSubdirectory("anchor-full-").FullName;
        try
        {
            foreach (var name in new[] { "07-trust-decay.dw", "TrustDecay.tla", "TrustDecay.cfg",
                                         "TrustDecay10.tla", "TrustDecay10.cfg" })
            {
                File.Copy(Path.Combine(aws1, name), Path.Combine(work, name));
            }

            var (exit, _, stderr) = await RunAsync("check", Path.Combine(work, "07-trust-decay.dw"),
                "--full", "--no-llm");

            // 1: the audit has findings -- both trust-decay claims are broken.
            Assert.True(exit == 1, $"exited {exit}: {stderr}");

            var report = Path.Combine(work, "07-trust-decay-findings", "findings.md");
            Assert.True(File.Exists(report), $"no report at {report}: {stderr}");
            Assert.False(File.Exists(Path.Combine(work, "findings.md")), "the directory's report was written");

            var text = File.ReadAllText(report);
            Assert.Contains("# Findings — `07-trust-decay.dw`", text);
            Assert.Contains("does not satisfy TrustDecay.tla", text);
            Assert.Contains("does not satisfy TrustDecay10.tla", text);
            Assert.Contains("| event-schema reading |", text);
        }
        finally
        {
            try { Directory.Delete(work, recursive: true); } catch (IOException) { /* scratch */ }
        }
    }

    /// <summary>
    /// --property with --full ADDS a module to the ones found by header rather than replacing them,
    /// and the report says which was which: a reader should know why a module is there.
    /// </summary>
    [CliPolicyFact]
    public async Task FullAddsAGivenPropertyToTheModulesItFinds()
    {
        var aws1 = Path.Combine(StdioTransportTests.Repo, "examples", "aws1");
        var work = Directory.CreateTempSubdirectory("anchor-full-").FullName;
        try
        {
            // TrustDecay10 beside the policy set, found by its header; TrustDecay left where it is
            // and named instead.
            foreach (var name in new[] { "07-trust-decay.dw", "TrustDecay10.tla", "TrustDecay10.cfg" })
            {
                File.Copy(Path.Combine(aws1, name), Path.Combine(work, name));
            }

            var (exit, _, stderr) = await RunAsync("check", Path.Combine(work, "07-trust-decay.dw"),
                "--full", "--no-llm", "--property", Path.Combine(aws1, "TrustDecay.tla"));

            Assert.True(exit == 1, $"exited {exit}: {stderr}");
            var text = File.ReadAllText(Path.Combine(work, "07-trust-decay-findings", "findings.md"));
            Assert.Contains("`TrustDecay.tla` (given with `--property`)", text);
            Assert.Contains("| `TrustDecay10.tla` |", text);
            Assert.Contains("| stated intentions (`.tla`) | 2 |", text);
        }
        finally
        {
            try { Directory.Delete(work, recursive: true); } catch (IOException) { /* scratch */ }
        }
    }

    static async Task<(int Exit, string Stdout, string Stderr)> RunAsync(params string[] args)
    {
        var info = new ProcessStartInfo("dotnet")
        {
            WorkingDirectory = StdioTransportTests.Repo,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        info.ArgumentList.Add(StdioTransportTests.CliDll);
        foreach (var arg in args)
        {
            info.ArgumentList.Add(arg);
        }

        using var process = Process.Start(info)!;

        // Both pipes read before waiting: a run that fills one while we block on the other
        // deadlocks, and a verbose check prints a great deal.
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        using var cts = new System.Threading.CancellationTokenSource(TimeSpan.FromMinutes(5));
        try
        {
            await process.WaitForExitAsync(cts.Token);
        }
        catch (OperationCanceledException)
        {
            process.Kill(entireProcessTree: true);
            throw new TimeoutException($"anchor {string.Join(' ', args)} did not finish in 5 minutes");
        }

        return (process.ExitCode, await stdout, await stderr);
    }

    #endregion
}

/// <summary>A fact needing the built CLI and the checker's toolchain: an interpreter and a JVM.</summary>
[AttributeUsage(AttributeTargets.Method)]
public sealed class CliPolicyFactAttribute : FactAttribute
{
    public CliPolicyFactAttribute()
    {
        var python = PythonProcess.FindPython();
        var java = TLCProcess.FindJava();

        Skip = !File.Exists(StdioTransportTests.CliDll)
                   ? $"the anchor CLI is not built at {StdioTransportTests.CliDll} — build the solution first"
             : !python.IsSuccess ? $"the policy checker needs Python: {python.Message}"
             : !java.IsSuccess ? $"the policy checker needs a JVM to run TLC: {java.Message}"
             : null!;
    }
}
