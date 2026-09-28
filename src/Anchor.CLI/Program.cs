namespace Anchor.CLI;

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

using CommandLine;

using Anchor.MCPServer;

/// <summary>
/// The Anchor command line, and the only entry point.
/// </summary>
/// <remarks>
/// <para>
/// <c>Anchor.MCPServer</c> is a library rather than a second executable. It had its own
/// <c>Program.cs</c> and its own argument parsing, which is two entry points to the same server and
/// therefore two parsers to keep in step. One binary, one set of flags.
/// </para>
/// <para>
/// <b>STANDARD OUTPUT IS A PROTOCOL STREAM UNDER STDIO</b>, and that shapes three decisions here
/// rather than one:
/// </para>
/// <list type="number">
/// <item>the log sink is chosen from the verb before anything can write, so stdio gets a file sink;</item>
/// <item><c>HelpWriter</c> is standard error, so a usage message triggered by a malformed launch
/// does not arrive at a host expecting JSON-RPC;</item>
/// <item><c>Console.Out</c> is redirected to standard error for the whole stdio session, so that a
/// stray <c>Console.WriteLine</c> anywhere beneath us lands somewhere harmless. The MCP transport
/// writes frames through the raw standard-output handle, which the redirection does not touch.</item>
/// </list>
/// <para>
/// The third is defence rather than tidiness: a single stray line makes the session malformed, and
/// the symptom is a host reporting a broken integration rather than anything naming the line. One
/// has already been caught here — a Serilog console sink under stdio — by a test that parses every
/// line the process writes.
/// </para>
/// </remarks>
public static class Program
{
    #region Methods

    public static async Task<int> Main(string[] args)
    {
        // A bare invocation is a request for help, not a request to serve. `server` is the default
        // verb because that is how an MCP host launches us, but a person typing `anchor` got a
        // process waiting silently on stdin — indistinguishable from a hang, and printing nothing,
        // because stdio keeps standard output clear for JSON-RPC framing.
        if (args.Length == 0)
        {
            args = ["--help"];
        }

        var verb = args.FirstOrDefault(a => !a.StartsWith('-'));

        // A default verb means an unrecognised one is not rejected: CommandLineParser binds the
        // stray token to `server` and starts it. `anchor frobnicate` exited 0 having silently begun
        // a stdio session on a closed pipe — a typo that looks like success and leaves no output to
        // explain itself. Checked here because the parser will not do it for us.
        if (verb is not null && !Verbs.Contains(verb))
        {
            Console.Error.WriteLine($"Unrecognised command '{verb}'. Try: {string.Join(", ", Verbs)}.");
            Console.Error.WriteLine("Run 'anchor --help' for usage.");
            return BadUsage;
        }

        // A verb whose product is a report on standard output, rather than MCP frames.
        var isReporting = verb is not null && Reporting.Contains(verb);
        var isHelp = args.Any(a => a is "--help" or "-h" or "--version");
        var isHttp = args.Contains("--http", StringComparer.OrdinalIgnoreCase);
        var isDebug = args.Contains("--debug", StringComparer.OrdinalIgnoreCase);

        // Everything but the stdio server may write to standard output. A reporting verb's report
        // IS its product, so it gets a console log sink only when debugging was asked for —
        // otherwise the log interleaves with the thing the reader is reading.
        var isStdioServer = !isReporting && !isHelp && !isHttp;

        if (isStdioServer || (isReporting && !isDebug))
        {
            Runtime.WithFileLogging("Anchor", "CLI", isDebug);
        }
        else
        {
            Runtime.WithFileAndConsoleLogging("Anchor", "CLI", isDebug);
        }

        // Usage and parse errors to standard error. The default is standard output, which under a
        // stdio launch would put a help screen where a host expects a handshake.
        var parser = new Parser(with =>
        {
            with.CaseInsensitiveEnumValues = true;
            with.HelpWriter = Console.Error;
        });

        try
        {
            return await parser
                .ParseArguments<ServerOptions, CheckOptions, ExplainOptions>(args)
                .MapResult(
                    (ServerOptions opts) => ServerAsync(opts),
                    (CheckOptions opts) => CheckAsync(opts),
                    (ExplainOptions opts) => ExplainAsync(opts),
                    errs => Task.FromResult(ParseFailure(errs)));
        }
        catch (Exception e)
        {
            Runtime.Fatal("anchor stopped: {0}", e.Message);

            // stderr even under stdio: it is not the protocol stream, so a host still sees why.
            Console.Error.WriteLine(e.Message);
            return CouldNotRun;
        }
    }

    /// <summary>Start the MCP server on the transport the flags asked for.</summary>
    static async Task<int> ServerAsync(ServerOptions opts)
    {
        var projectDir = Blank(opts.ProjectDir);
        var anchorRoot = Blank(opts.AnchorRoot);

        if (opts.Http)
        {
            await AnchorMCPServer.RunHttpAsync(opts.Port, projectDir, anchorRoot);
            return Ok;
        }

        // Standard output belongs to the protocol and to nothing else, so it is taken away from
        // everything else for the duration. Not paranoia: a logger writes to the console unless
        // file logging happened to be configured first, and one stray line makes every frame after
        // it suspect. Anything that does print lands on stderr, where a person running this by hand
        // can still see it. The MCP transport is unaffected — it holds the raw stdout stream, not
        // this TextWriter.
        var protocol = Console.Out;
        Console.SetOut(Console.Error);
        try
        {
            await AnchorMCPServer.RunStdioAsync(projectDir, anchorRoot);
            return Ok;
        }
        finally
        {
            Console.SetOut(protocol);
        }
    }

    /// <summary>
    /// Model-check a policy, and hand back the checker's own verdict — text and exit code both.
    /// </summary>
    /// <remarks>
    /// A faithful pass-through rather than a re-interpretation. The checker's exit code already
    /// encodes whether it ANSWERED (see <c>PolicyTools.Answered</c>), and a script calling
    /// <c>anchor check</c> should be able to branch on the same values the Python entry point gives
    /// it. Only "the checker could not be started at all" is ours to add, because the checker cannot
    /// report that about itself.
    /// </remarks>
    static async Task<int> CheckAsync(CheckOptions opts)
    {
        // THE ARGUMENT'S SHAPE DECIDES, not a flag. A directory is audited; a file is checked rule
        // by rule. `pipeline.sweep()` already reads a path both ways, and a flag would be a second
        // thing to get wrong beside a path that already says which it is.
        if (Directory.Exists(opts.Policy))
        {
            return await AuditAsync(opts);
        }

        // Refused rather than ignored. These do nothing for a single policy set, and an option that
        // silently does nothing is worse than one that is not there.
        foreach (var (name, given) in new[]
                 {
                     ("--output-dir", !string.IsNullOrWhiteSpace(opts.OutputDir)),
                     ("--no-llm", opts.NoLlm),
                     ("--provider", !string.IsNullOrWhiteSpace(opts.Provider)),
                     ("--llm", !string.IsNullOrWhiteSpace(opts.Llm))
                 })
        {
            if (given)
            {
                Console.Error.WriteLine($"{name} applies to a directory, not a single policy set.");
                return BadUsage;
            }
        }

        // No containment unless asked for: a person running this on their own machine is not the
        // agent that the MCP server's project directory exists to fence in.
        var tools = new PolicyTools(Blank(opts.ProjectDir), Blank(opts.AnchorRoot));

        PolicyCheckResult result;
        try
        {
            result = await tools.CheckPolicyAsync(
                opts.Policy,
                against: Blank(opts.Against),
                eventSchema: Blank(opts.EventSchema),
                property: Blank(opts.Property),
                attempts: opts.Attempts,
                amount: opts.Amount,
                maxFields: opts.MaxFields,
                syntax: opts.Syntax ? true : null,
                explain: opts.Explain ? true : null,
                witness: opts.Witness ? true : null,
                verbose: opts.Verbose ? true : null,
                trace: opts.Trace ? true : null,
                keep: Blank(opts.Keep),
                smoke: opts.Smoke,
                timeoutSeconds: opts.Timeout);
        }
        catch (ArgumentException e)
        {
            // A path that escaped --project-dir, which is only reachable when one was given.
            Console.Error.WriteLine(e.Message);
            return BadUsage;
        }

        if (!string.IsNullOrWhiteSpace(result.Output))
        {
            Console.Write(result.Output);
        }

        if (result.Error is not null)
        {
            Console.Error.WriteLine(result.Error);
        }

        // Null means the checker never started — a missing interpreter or JVM, which is neither a
        // verdict nor a refusal and must not be mistaken for either.
        return result.ExitCode ?? CouldNotRun;
    }

    /// <summary>
    /// Audit a directory of policies unattended, and write the findings into it.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Shells out to <c>src/agent/audit.py</c> for the same reason <c>check</c> shells out to the
    /// checker: the orchestration is Python because everything it orchestrates is. The exit code is
    /// passed through unchanged — 1 means findings, 3 means the run could not happen, and
    /// collapsing those would make this useless in a pipeline.
    /// </para>
    /// <para>
    /// <b>It answers to <c>check &lt;directory&gt;</c> rather than to a verb of its own.</b> It was
    /// <c>auto</c>, and that name claimed the wrong thing: "auto" means autoformalization in this
    /// field and nothing here formalizes anything — every intentional claim it checks is a
    /// <c>.tla</c> module a person wrote by hand. What was automated was the running.
    /// </para>
    /// </remarks>
    static async Task<int> AuditAsync(CheckOptions opts)
    {
        var args = new List<string> { opts.Policy };

        if (!string.IsNullOrWhiteSpace(opts.OutputDir)) args.AddRange(["--output-dir", opts.OutputDir]);
        if (!string.IsNullOrWhiteSpace(opts.Provider)) args.AddRange(["--provider", opts.Provider]);
        if (!string.IsNullOrWhiteSpace(opts.Llm)) args.AddRange(["--llm", opts.Llm]);
        if (opts.Attempts is int a) args.AddRange(["--attempts", a.ToString()]);
        if (opts.Smoke is int sm) args.AddRange(["--smoke", sm.ToString()]);
        if (opts.MaxFields is int mf) args.AddRange(["--max-fields", mf.ToString()]);
        if (opts.NoLlm) args.Add("--no-llm");
        if (opts.AllowFlaggedInput) args.Add("--allow-flagged-input");

        // No timeout of our own: a directory of policies is minutes of TLC per policy, and a cap
        // here would kill a run that was working. The script bounds each check itself.
        var r = await PythonProcess.RunAsync(PolicyTools.AuditScript, [.. args],
            root: Blank(opts.AnchorRoot), timeout: TimeSpan.FromHours(6));

        if (!r.IsSuccess)
        {
            Console.Error.WriteLine(r.Message ?? "the directory audit could not be run");
            return CouldNotRun;
        }

        if (!string.IsNullOrWhiteSpace(r.Value.Output)) Console.Write(r.Value.Output);
        if (!string.IsNullOrWhiteSpace(r.Value.ErrorOutput)) Console.Error.Write(r.Value.ErrorOutput);
        return r.Value.ExitCode;
    }

    /// <summary>
    /// Say what a property module forbids, without checking anything.
    /// </summary>
    /// <remarks>
    /// The exit code is the explainer's own: <b>4</b> means a claim cannot fail, which is a finding
    /// and not an error — it is the same number <c>check --property --mutation-score</c> uses for
    /// the same defect found the expensive way, so a pipeline can branch on one value however it
    /// was reached.
    /// </remarks>
    static async Task<int> ExplainAsync(ExplainOptions opts)
    {
        var args = new List<string> { opts.Module };

        if (!string.IsNullOrWhiteSpace(opts.Config)) args.AddRange(["--cfg", opts.Config]);
        if (opts.Json) args.Add("--json");

        // Seconds, not minutes: this reads a file. A generous cap still catches a hang without
        // ever cutting short work that was progressing.
        var r = await PythonProcess.RunAsync(PolicyTools.ExplainScript, [.. args],
            root: Blank(opts.AnchorRoot), timeout: TimeSpan.FromMinutes(2));

        if (!r.IsSuccess)
        {
            Console.Error.WriteLine(r.Message ?? "the property could not be read");
            return CouldNotRun;
        }

        if (!string.IsNullOrWhiteSpace(r.Value.Output)) Console.Write(r.Value.Output);
        if (!string.IsNullOrWhiteSpace(r.Value.ErrorOutput)) Console.Error.Write(r.Value.ErrorOutput);
        return r.Value.ExitCode;
    }

    /// <summary>
    /// A parse failure, or a request for help. Help is a success; anything else is bad usage.
    /// </summary>
    /// <remarks>
    /// <b>2, not 1.</b> 1 already means "a <c>--property</c> claim is BROKEN", and a script must be
    /// able to tell "you typed it wrong" from "the policy does not mean what you said it means".
    /// This is the one place this CLI's exit codes deliberately differ from Polson's.
    /// </remarks>
    static int ParseFailure(IEnumerable<Error> errors)
    {
        var asked = errors.All(e =>
            e is HelpRequestedError or HelpVerbRequestedError or VersionRequestedError);

        return asked ? Ok : BadUsage;
    }

    /// <summary>CommandLineParser gives an unset string as empty; the API below wants null.</summary>
    static string? Blank(string value) => string.IsNullOrWhiteSpace(value) ? null : value;

    #endregion

    #region Fields

    /// <summary>
    /// Every verb this binary answers to, including the two CommandLineParser adds itself. Anything
    /// else is refused rather than absorbed by the default verb.
    /// </summary>
    static readonly HashSet<string> Verbs = new(StringComparer.OrdinalIgnoreCase)
    {
        "server", "check", "explain", "help", "version"
    };

    /// <summary>
    /// The verbs whose product is a report on standard output. They get a file log sink unless
    /// --debug asked otherwise, so that logging never interleaves with the thing being read.
    /// </summary>
    static readonly HashSet<string> Reporting = new(StringComparer.OrdinalIgnoreCase)
    {
        "check", "explain"
    };

    const int Ok = 0;

    /// <summary>Bad usage: a parse error, or a path outside <c>--project-dir</c>.</summary>
    const int BadUsage = 2;

    /// <summary>The tool could not be started at all. Distinct from anything it might have said.</summary>
    const int CouldNotRun = 3;

    #endregion
}
