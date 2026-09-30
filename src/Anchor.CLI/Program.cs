namespace Anchor.CLI;

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
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

        // An option that takes a value, given none, is dropped by CommandLineParser without a word:
        // `--event-schema` alone ran under the default reading, `--llm` alone under the default
        // model, `--attempts` alone under the default bound. Checked here for the same reason.
        if (MissingValue(verb, args) is string bare)
        {
            Console.Error.WriteLine($"{bare} needs a value.");
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
        // Opposite readings, refused here because the checker is handed one tri-state rather than
        // two flags, and "both" is not a state it can be given.
        if (opts.Pinned && opts.Unpinned)
        {
            Console.Error.WriteLine("--pinned and --unpinned are opposite readings; pass one.");
            return BadUsage;
        }

        // ONE FLAG, ONE MEANING, WHICHEVER THE SHAPE. Without --full a policy set or a directory is
        // checked rule by rule and printed, and nothing is written; with it, either is audited and
        // written up. The shape used to decide -- a directory was always audited -- which left a
        // single policy set with no way to be audited and read as though it could not use an LLM.
        // Every option that means something in only one mode is refused in the other, never
        // ignored: an option that silently does nothing is worse than one that is not there.
        if (opts.Full)
        {
            // --property joins an audit of ONE policy set; for a directory there is no telling which
            // set it is about, and a module whose header says so is found without it.
            return Refused(WithoutFullOnly(opts), "applies to a check without --full")
                ?? (Directory.Exists(opts.Policy)
                    ? Refused([("--property", !string.IsNullOrWhiteSpace(opts.Property))],
                              "applies to a single policy set file, not a directory")
                    : null)
                ?? await AuditAsync(opts);
        }
        if (Refused(FullOnly(opts), "applies only with --full") is int notFull)
        {
            return notFull;
        }
        if (Directory.Exists(opts.Policy))
        {
            return Refused(PolicySetOnly(opts), "applies to a single policy set file, not a directory")
                ?? await CheckDirectoryAsync(opts);
        }

        if (File.Exists(opts.Policy))
        {
            Console.Error.WriteLine(Announce(opts, 1));
        }
        var code = await CheckOneAsync(opts, opts.Policy);
        await ListAvailableAsync(opts, opts.Policy);
        return code;
    }

    /// <summary>
    /// A plain check of every policy set in a directory, one after another, then what --full would
    /// add. The worst answer wins: exit codes are ordered so that the larger is the worse, and one
    /// policy set that could not be checked leaves the directory unanswered.
    /// </summary>
    static async Task<int> CheckDirectoryAsync(CheckOptions opts)
    {
        // By extension rather than by pattern alone: Windows matches "*.dw" loosely, and the audit
        // this mirrors globs exactly.
        var sets = Directory.GetFiles(opts.Policy, "*.dw")
            .Where(f => Path.GetExtension(f).Equals(".dw", StringComparison.OrdinalIgnoreCase))
            .Order(StringComparer.Ordinal)
            .ToArray();
        if (sets.Length == 0)
        {
            Console.Error.WriteLine($"no .dw policy sets in {opts.Policy}");
            return CouldNotRun;
        }

        Console.Error.WriteLine(Announce(opts, sets.Length));
        var worst = Ok;
        foreach (var set in sets)
        {
            Console.WriteLine($"==== {Path.GetFileName(set)} ".PadRight(78, '='));
            worst = Math.Max(worst, await CheckOneAsync(opts, set));
            Console.WriteLine();
        }
        await ListAvailableAsync(opts, opts.Policy);
        return worst;
    }

    /// <summary>
    /// What --full would add: the property modules and questions a plain check skipped. Found by the
    /// audit's own discovery, so the list and the audit cannot disagree about what is there.
    /// </summary>
    static async Task ListAvailableAsync(CheckOptions opts, string target)
    {
        var r = await PythonProcess.RunAsync(PolicyTools.AuditScript, [Path.GetFullPath(target), "--list"],
            root: Blank(opts.AnchorRoot), timeout: TimeSpan.FromMinutes(1));
        if (!r.IsSuccess || !r.Value.Succeeded)
        {
            // Not fatal -- the verdicts above stand -- and not silent either.
            Console.Error.WriteLine("(could not list the property modules and questions --full would use)");
            return;
        }
        if (!string.IsNullOrWhiteSpace(r.Value.Output))
        {
            Console.WriteLine();
            Console.Write(r.Value.Output);
        }
    }

    /// <summary>
    /// What a plain check is about to do, from the options it was given. On stderr, before the first
    /// TLC run, so the verdicts on stdout stay exactly as they were. The audit says the same of
    /// itself, in the same layout.
    /// </summary>
    static string Announce(CheckOptions o, int sets)
    {
        static string Row(string label, string text) => $"  {label,-18}{text}";
        var pad = new string(' ', 20);
        var what = sets == 1 ? "one policy set" : $"{sets} policy sets";

        var task = !string.IsNullOrWhiteSpace(o.Property)
            ? Row("claims", $"the invariants of {Path.GetFileName(o.Property)}, instead of rule by rule" +
                            (o.Explain ? "; each explained first" : "") +
                            (o.Witness ? "; a BROKEN one replayed in Dogwood" : ""))
            : !string.IsNullOrWhiteSpace(o.Against)
            ? Row("compared", $"against {Path.GetFileName(o.Against)}: MORE or LESS PERMISSIVE, " +
                              "EQUIVALENT or INCOMPARABLE")
            : Row("rule by rule", "one or two TLC runs per rule");
        var bound = o.Smoke is int n
            ? $"a random walk of {n} behaviours (--smoke): finds live rules, never VACUOUS, REDUNDANT or DEAD"
            : $"exhaustive, sessions of up to {o.Attempts ?? 3} attempts";
        var reading = !string.IsNullOrWhiteSpace(o.EventSchema) ? $"the event schema {Path.GetFileName(o.EventSchema)}"
            : o.Unpinned ? "unpinned: every principal's events"
            : o.Pinned ? "callerPrincipal pinned, Dogwood's default"
            : "callerPrincipal pinned, Dogwood's default (--unpinned or --event-schema to change)";

        List<string> lines = [$"Check of {o.Policy} ({what}):", task, pad + bound, pad + "reading: " + reading];
        if (o.Syntax) lines.Add(pad + "parsed by `dogwood check-parse` first (--syntax)");
        if (!string.IsNullOrWhiteSpace(o.Keep)) lines.Add(pad + $"the generated TLA+ kept in {o.Keep}");
        lines.Add("Prints the verdicts" + (string.IsNullOrWhiteSpace(o.Keep) ? ", writes nothing" : "") +
                  " and asks no LLM; --full audits and writes a report.");
        return string.Join(Environment.NewLine, lines) + Environment.NewLine;
    }

    /// <summary>The first option given that does not apply here, reported, as an exit code; or null.</summary>
    static int? Refused(IEnumerable<(string Name, bool Given)> options, string why)
    {
        foreach (var (name, given) in options)
        {
            if (given)
            {
                Console.Error.WriteLine($"{name} {why}.");
                return BadUsage;
            }
        }
        return null;
    }

    /// <summary>What only an audit uses: where it writes, and the LLM it asks.</summary>
    static (string, bool)[] FullOnly(CheckOptions o) =>
    [
        ("--output-dir", !string.IsNullOrWhiteSpace(o.OutputDir)),
        ("--no-llm", o.NoLlm),
        ("--provider", !string.IsNullOrWhiteSpace(o.Provider)),
        ("--llm", !string.IsNullOrWhiteSpace(o.Llm)),
        ("--config", !string.IsNullOrWhiteSpace(o.Config)),
        ("--allow-flagged-input", o.AllowFlaggedInput)
    ];

    /// <summary>What names one policy set's own inputs or outputs, so means nothing for many.</summary>
    static (string, bool)[] PolicySetOnly(CheckOptions o) =>
    [
        ("--against", !string.IsNullOrWhiteSpace(o.Against)),
        ("--property", !string.IsNullOrWhiteSpace(o.Property)),
        ("--explain", o.Explain),
        ("--witness", o.Witness),
        ("--trace", o.Trace),
        ("--keep", !string.IsNullOrWhiteSpace(o.Keep))
    ];

    /// <summary>
    /// What an audit does not take: the single-set options it replaces with its own witnesses and
    /// traces/, and the knobs its checker runs do not expose. Not --property, which an audit of one
    /// policy set adds to the modules it finds.
    /// </summary>
    static (string, bool)[] WithoutFullOnly(CheckOptions o) =>
    [
        .. PolicySetOnly(o).Where(option => option.Item1 != "--property"),
        ("--syntax", o.Syntax),
        ("--verbose", o.Verbose),
        ("--amount", o.Amount is not null),
        ("--timeout", o.Timeout is not null)
    ];

    /// <summary>One policy set, checked rule by rule and printed. Writes nothing.</summary>
    static async Task<int> CheckOneAsync(CheckOptions opts, string policy)
    {
        // No containment unless asked for: a person running this on their own machine is not the
        // agent that the MCP server's project directory exists to fence in.
        var tools = new PolicyTools(Blank(opts.ProjectDir), Blank(opts.AnchorRoot))
        {
            // Which TLC run is starting, as it starts: a policy set with many rules is a minute of
            // silence otherwise. On stderr, so the verdicts on stdout stay exactly as they were.
            Progress = Console.Error.WriteLine
        };

        PolicyCheckResult result;
        try
        {
            result = await tools.CheckPolicyAsync(
                policy,
                against: Blank(opts.Against),
                eventSchema: Blank(opts.EventSchema),
                pinned: opts.Pinned ? true : opts.Unpinned ? false : null,
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
    /// Audit a policy set or a directory of them unattended, and write the findings up: <c>check --full</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Shells out to <c>src/agent/audit.py</c> for the same reason <c>check</c> shells out to the
    /// checker: the orchestration is Python because everything it orchestrates is. The exit code is
    /// passed through unchanged — 1 means findings, 3 means the run could not happen, and
    /// collapsing those would make this useless in a pipeline.
    /// </para>
    /// <para>
    /// <b>It answers to <c>check --full</c> rather than to a verb of its own.</b> It was
    /// <c>auto</c>, and that name claimed the wrong thing: "auto" means autoformalization in this
    /// field and nothing here formalizes anything — every intentional claim it checks is a
    /// <c>.tla</c> module a person wrote by hand. What was automated was the running.
    /// </para>
    /// </remarks>
    static async Task<int> AuditAsync(CheckOptions opts)
    {
        // FULL PATHS, because the script runs from the Anchor root -- /app in the container -- and
        // a path as typed is relative to wherever the user is. `check my-policies --full` from /work
        // looked for /app/my-policies.
        var args = new List<string> { Path.GetFullPath(opts.Policy) };

        if (!string.IsNullOrWhiteSpace(opts.OutputDir)) args.AddRange(["--output-dir", Path.GetFullPath(opts.OutputDir)]);
        if (!string.IsNullOrWhiteSpace(opts.EventSchema)) args.AddRange(["--event-schema", Path.GetFullPath(opts.EventSchema)]);
        if (!string.IsNullOrWhiteSpace(opts.Property)) args.AddRange(["--property", Path.GetFullPath(opts.Property)]);
        if (!string.IsNullOrWhiteSpace(opts.Provider)) args.AddRange(["--provider", opts.Provider]);
        if (!string.IsNullOrWhiteSpace(opts.Llm)) args.AddRange(["--llm", opts.Llm]);
        if (!string.IsNullOrWhiteSpace(opts.Config)) args.AddRange(["--config", Path.GetFullPath(opts.Config)]);
        if (opts.Attempts is int a) args.AddRange(["--attempts", a.ToString()]);
        if (opts.Smoke is int sm) args.AddRange(["--smoke", sm.ToString()]);
        if (opts.MaxFields is int mf) args.AddRange(["--max-fields", mf.ToString()]);
        if (opts.Pinned) args.Add("--pinned");
        if (opts.Unpinned) args.Add("--unpinned");
        if (opts.NoLlm) args.Add("--no-llm");
        if (opts.AllowFlaggedInput) args.Add("--allow-flagged-input");

        // No timeout of our own: a directory of policies is minutes of TLC per policy, and a cap
        // here would kill a run that was working. The script bounds each check itself.
        // STREAMED, not printed at the end: an audit is minutes of TLC, and printing its progress
        // only once it had finished made every line of it arrive together, after a long silence.
        var r = await PythonProcess.RunAsync(PolicyTools.AuditScript, [.. args],
            root: Blank(opts.AnchorRoot), timeout: TimeSpan.FromHours(6),
            onOutput: Console.WriteLine, onError: Console.Error.WriteLine);

        if (!r.IsSuccess)
        {
            Console.Error.WriteLine(r.Message ?? "the audit could not be run");
            return CouldNotRun;
        }
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
            Console.Error.WriteLine(r.Message ?? "the property module could not be read");
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

    /// <summary>
    /// The first option that takes a value but was given none -- last on the line, followed by
    /// another option, or <c>--name=</c> -- or null. Anything not a bool takes a value.
    /// </summary>
    static string? MissingValue(string? verb, string[] args)
    {
        var type = OptionTypes.FirstOrDefault(t => t.GetCustomAttribute<VerbAttribute>() is { } v
            && (verb is null ? v.IsDefault : string.Equals(v.Name, verb, StringComparison.OrdinalIgnoreCase)));
        if (type is null)
        {
            return null;
        }

        var takesValue = type.GetProperties()
            .Where(p => p.PropertyType != typeof(bool))
            .Select(p => p.GetCustomAttribute<OptionAttribute>()?.LongName)
            .OfType<string>()
            .Select(name => "--" + name)
            .ToHashSet();

        for (var i = 0; i < args.Length; i++)
        {
            var (name, value) = args[i].Split('=', 2) is [var n, var v]
                ? (n, v)
                : (args[i], i + 1 < args.Length && !args[i + 1].StartsWith("--") ? args[i + 1] : null);
            if (takesValue.Contains(name) && string.IsNullOrEmpty(value))
            {
                return name;
            }
        }
        return null;
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
    /// <summary>The option types the parser is given, for reading their options before it runs.</summary>
    static readonly Type[] OptionTypes = [typeof(ServerOptions), typeof(CheckOptions), typeof(ExplainOptions)];

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
