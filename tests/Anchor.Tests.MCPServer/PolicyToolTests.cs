namespace Anchor.Tests.MCPServer;

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

using Anchor.MCPServer;
using Anchor.Verifiers.TLAPlus;

/// <summary>
/// The MCP server's policy tools, held to the command line they wrap.
/// </summary>
/// <remarks>
/// <para>
/// THE POINT OF THE DIFFERENTIAL. The checker's CLI is the interface this project documents, tests
/// and reasons about; the MCP tool is a second way to reach the same code, and a second way to
/// reach the same code is a second chance to get a different answer. Argument marshalling, path
/// resolution and output parsing all sit between an agent and the verdict, and each of them could
/// silently change it — an argument dropped, a flag not forwarded, a verdict line not matched.
/// </para>
/// <para>
/// So these run both and compare. The CLI side starts its own process against the documented
/// invocation and shares nothing with <see cref="PythonProcess"/> but the interpreter path — which
/// is discovery rather than behaviour, and is not what the comparison is about.
/// </para>
/// <para>
/// SKIPPED WITHOUT THE TOOLCHAIN. The checker needs an interpreter and a JVM, because it runs TLC
/// once per rule. Skipping is visible in the run summary; passing quietly would be worse than not
/// having the test.
/// </para>
/// </remarks>
public class PolicyToolTests : TestsRuntime
{
    #region Methods

    /// <summary>Discovery, on its own, so a toolchain failure does not present as a wrong verdict.</summary>
    [PolicyCheck]
    public void TheToolchainIsFound()
    {
        var root = PythonProcess.FindRoot();
        Assert.True(root.IsSuccess, root.Message);
        Assert.True(File.Exists(Path.Combine(root.Value, "Anchor.sln")), $"not an Anchor tree: {root.Value}");

        var python = PythonProcess.FindPython();
        Assert.True(python.IsSuccess, python.Message);

        // Importable, not merely present — the modules the checker actually needs.
        Assert.True(PythonProcess.CanImport("re"), "the interpreter cannot import re");
    }

    /// <summary>
    /// The tool and the command line must produce the same text, rule for rule. Compared whole
    /// rather than verdict-by-verdict: a caveat line the tool dropped would still leave the
    /// verdicts matching, and the caveat is the part an agent most needs.
    /// </summary>
    [PolicyCheck]
    public async Task CheckPolicyAgreesWithTheCommandLine()
    {
        foreach (var fixture in new[] { "dead_forbid.dw", "redundant_permit.dw" })
        {
            var direct = await RunCheckerDirectlyAsync(fixture);
            var tool = await Tools().CheckPolicyAsync(Path.Combine("tests", "policies", fixture));

            Assert.True(tool.Answered, tool.Error);
            Assert.Equal(Normalize(direct), Normalize(tool.Output));
        }
    }

    /// <summary>
    /// The structured findings must say what the text says. Parsed here by an independent
    /// expression, so a bug in the tool's own parser cannot agree with itself.
    /// </summary>
    [PolicyCheck]
    public async Task StructuredFindingsMatchTheText()
    {
        var tool = await Tools().CheckPolicyAsync(Path.Combine("tests", "policies", "dead_forbid.dw"));
        Assert.True(tool.Answered, tool.Error);

        var fromText = Regex.Matches(tool.Output.Replace("\r\n", "\n"),
                @"^\s+(permit|forbid) #(\d+)\b.*?\s(VACUOUS|REDUNDANT|DEAD|live)\b", RegexOptions.Multiline)
            .Select(m => (Effect: m.Groups[1].Value, Rule: int.Parse(m.Groups[2].Value), Verdict: m.Groups[3].Value))
            .ToList();

        Assert.NotEmpty(fromText);
        Assert.Equal(fromText,
            tool.Findings.Select(f => (f.Effect, f.Rule, f.Verdict)).ToList());

        // The fixture's whole purpose: a forbid that denies nothing the rest of the set would allow.
        var dead = Assert.Single(tool.Inert);
        Assert.Equal("DEAD", dead.Verdict);
        Assert.Equal("forbid", dead.Effect);
    }

    /// <summary>
    /// A policy outside the modelled subset is REFUSED, and the refusal must not read as a clean
    /// bill of health. This is the failure mode that matters most: <c>Answered</c> false with an
    /// empty finding list, versus "no findings" — which an agent would summarise as "no problems".
    /// </summary>
    [PolicyCheck]
    public async Task ARefusedPolicyIsNotAnEmptyPass()
    {
        var tool = await Tools().CheckPolicyAsync(Path.Combine("tests", "policies", "like_impossible.dw"));

        Assert.False(tool.Answered);
        Assert.Empty(tool.Findings);
        Assert.NotNull(tool.Error);
        Assert.Contains("REFUSED", tool.Error);

        // The reason, not just the refusal — it names the construct, which is what makes it
        // actionable rather than a wall.
        Assert.Contains("glob intersection", tool.Error);
    }

    /// <summary>
    /// Without an event schema the checker says every answer is under Dogwood's default reading, and
    /// the tool must carry that out separately. It is the single most droppable line in the output
    /// and the most expensive to drop.
    /// </summary>
    [PolicyCheck]
    public async Task TheReadingCaveatSurvivesTheToolBoundary()
    {
        var tool = await Tools().CheckPolicyAsync(Path.Combine("tests", "policies", "dead_forbid.dw"));

        Assert.True(tool.Answered, tool.Error);
        Assert.NotNull(tool.Reading);
        Assert.Contains("Dogwood's own default", tool.Reading, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("callerPrincipal", tool.Reading, StringComparison.Ordinal);
    }

    /// <summary>
    /// A path escaping the project is refused. The checker prints the policy it read, so a tool
    /// that will read any file on the host is a file-disclosure tool wearing a verifier's name.
    /// </summary>
    [Fact]
    public async Task APathOutsideTheProjectIsRefused()
    {
        var tools = new PolicyTools(projectRoot: Path.Combine(Repo, "tests", "policies"));

        // Its own type, which is what the server's tool filter answers as a refusal rather than
        // letting the SDK log it as an unhandled failure.
        var escape = await Assert.ThrowsAsync<OutsideProjectException>(
            () => tools.CheckPolicyAsync(Path.Combine("..", "..", "CLAUDE.md")));
        Assert.Contains("outside this project's directory", escape.Message);

        // The same containment on every path-bearing parameter, not only the first.
        var viaSchema = await Assert.ThrowsAsync<OutsideProjectException>(
            () => tools.CheckPolicyAsync("dead_forbid.dw", eventSchema: Path.Combine("..", "..", "CLAUDE.md")));
        Assert.Contains("outside this project's directory", viaSchema.Message);
    }

    /// <summary>A missing policy is reported as such, rather than as a policy with no rules.</summary>
    [PolicyCheck]
    public async Task AMissingPolicyIsNotAnEmptyPass()
    {
        var tool = await Tools().CheckPolicyAsync(Path.Combine("tests", "policies", "no_such_policy.dw"));

        Assert.False(tool.Answered);
        Assert.Empty(tool.Findings);
        Assert.Contains("no such policy file", tool.Error ?? "");
    }

    /// <summary>
    /// The documented command line, run as a human runs it: a process of its own, arguments as the
    /// README gives them, nothing shared with the code under test but the interpreter path.
    /// </summary>
    static async Task<string> RunCheckerDirectlyAsync(string fixture)
    {
        var python = PythonProcess.FindPython();
        Assert.True(python.IsSuccess, python.Message);

        var info = new ProcessStartInfo(python.Value)
        {
            WorkingDirectory = Repo,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        info.ArgumentList.Add("src/checker/properties.py");
        info.ArgumentList.Add($"tests/policies/{fixture}");

        var output = new StringBuilder();
        using var process = new Process { StartInfo = info };
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) output.AppendLine(e.Data); };

        process.Start();
        process.BeginOutputReadLine();
        var stderr = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();

        Assert.True(process.ExitCode == 0, $"the checker exited {process.ExitCode}\n{output}\n{stderr}");
        return output.ToString();
    }

    static PolicyTools Tools() => new(projectRoot: Repo);

    /// <summary>Line endings only. Anything else differing is the thing being looked for.</summary>
    static string Normalize(string text) => text.Replace("\r\n", "\n").TrimEnd();

    #endregion

    #region Fields

    static readonly string Repo = PythonProcess.FindRoot().IsSuccess
        ? PythonProcess.FindRoot().Value : Directory.GetCurrentDirectory();

    /// <summary>
    /// SANY's output becomes one diagnostic per error, with where it is.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The shape is taken from the TLA+ VS Code extension's own MCP surface, which returns a
    /// message per error rather than a wall of text — with more of the location kept, because SANY
    /// gives a line, a column range and the module, and dropping them throws away the part an agent
    /// can act on.
    /// </para>
    /// <para>
    /// <b>Both shapes matter and they are different.</b> A semantic error carries a location; an
    /// ABORT — a module that will not parse at all — carries none, and is returned with line 0
    /// rather than dropped, because it is the case an agent most needs told about. A parser that
    /// handled only the first would go silent on exactly the worst input.
    /// </para>
    /// <para>
    /// Fixtures are SANY's real output, copied from a run, not invented.
    /// </para>
    /// </remarks>
    [Fact]
    public void SanyOutputBecomesDiagnostics()
    {
        const string semantic = """
            *** Errors: 1

            line 47, col 58 to line 47, col 62 of module typo

            Unknown operator: `Grant'.
            """;

        var one = Assert.Single(PolicyTools.Diagnostics(semantic));
        Assert.Equal(47, one.Line);
        Assert.Equal(58, one.Column);
        Assert.Equal("typo", one.Module);
        Assert.Contains("Unknown operator", one.Message);

        const string abort = """
            tla2sany.semantic.AbortException
            *** Abort messages: 1

            In module unbalanced

            Could not parse module unbalanced from file unbalanced.tla
            """;

        var aborted = Assert.Single(PolicyTools.Diagnostics(abort));
        Assert.Equal(0, aborted.Line);
        Assert.Equal("unbalanced", aborted.Module);
        Assert.Contains("Could not parse", aborted.Message);

        // A clean run has nothing to report, and must not manufacture a diagnostic from the
        // success banner.
        Assert.Empty(PolicyTools.Diagnostics(
            "****** SANY2 Version 2.1 created 24 February 2014\nSemantic processing of module firewall"));
    }

    /// <summary>
    /// The reading a verdict was reached under reaches the caller, for each way the checker words it.
    /// </summary>
    /// <remarks>
    /// The AgentCore reading is chosen FOR the caller, from the policy text, so it is the one most
    /// worth reporting and the one a parser written for the other two would drop. Fixtures are the
    /// checker's real banners.
    /// </remarks>
    [Fact]
    public void TheReadingIsReportedWhicheverWayItWasChosen()
    {
        const string agentcore = """
            the policy binds eventResource/eventPrincipal, so every answer below uses
              AgentCore's event schema: history partitioned by session, and one gateway
              in the model -- a rule scoped to it applies to every request.
            """;
        Assert.Contains("AgentCore's event schema", PolicyTools.Reading(agentcore));

        const string fallback = """
            no --event-schema given, so every answer below uses Dogwood's own default
              reading: callerPrincipal pinned on every kind.
            """;
        Assert.Contains("callerPrincipal", PolicyTools.Reading(fallback));

        Assert.Equal("under prod.dwschema: partitioned by sessionId -- a temporal predicate sees only its own partition",
                     PolicyTools.Reading("under prod.dwschema: partitioned by sessionId -- a temporal predicate sees only its own partition\n"));
    }

    #endregion
}

/// <summary>
/// A fact needing the policy checker: an interpreter and a JVM, because the checker runs TLC once
/// per rule.
/// </summary>
/// <remarks>
/// Decided at discovery, which is the only dynamic skip xunit v2 offers without another package —
/// and packages are installed by hand here, never automatically.
/// </remarks>
[AttributeUsage(AttributeTargets.Method)]
public sealed class PolicyCheckAttribute : FactAttribute
{
    public PolicyCheckAttribute()
    {
        var root = PythonProcess.FindRoot();
        var python = PythonProcess.FindPython();
        var java = TLCProcess.FindJava();

        Skip = !root.IsSuccess ? $"the policy checker needs the Anchor tree: {root.Message}"
             : !python.IsSuccess ? $"the policy checker needs Python: {python.Message}"
             : !java.IsSuccess ? $"the policy checker needs a JVM to run TLC: {java.Message}"
             : null!;
    }
}
