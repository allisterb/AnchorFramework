namespace Anchor.MCPServer;

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

using ModelContextProtocol.Server;

/// <summary>
/// The policy-checking tools: Dogwood policy text in, a model-checked verdict out.
/// </summary>
/// <remarks>
/// Every tool here runs the Python checker out of process through <see cref="PythonProcess"/>. That
/// is not a stopgap — see its remarks — and it means a tool call costs a process start plus however
/// long TLC takes, which is seconds rather than milliseconds. Tool descriptions say so, because an
/// agent that expects a millisecond call will retry a slow one.
/// </remarks>
[McpServerToolType]
public partial class PolicyTools : Runtime
{
    #region Constructors

    public PolicyTools(string? projectRoot = null, string? anchorRoot = null)
    {
        ProjectRoot = projectRoot is null ? null : Path.GetFullPath(projectRoot);
        AnchorRoot = anchorRoot;
    }

    #endregion

    #region Properties

    /// <summary>The directory agent-supplied paths are resolved inside. Null means no containment.</summary>
    public string? ProjectRoot { get; }

    /// <summary>The Anchor tree the checker is run from. Null lets <see cref="PythonProcess"/> find it.</summary>
    public string? AnchorRoot { get; }

    /// <summary>
    /// Where the checker's progress lines go as each TLC run starts, or null for none. The CLI
    /// sets it; the MCP server does not, because an agent reads the answer rather than a running
    /// commentary, and the stderr a refusal is parsed from then stays exactly as it was.
    /// </summary>
    public Action<string>? Progress { get; init; }

    #endregion

    #region Methods

    [McpServerTool(Name = "CheckPolicy")]
    [Description(
        "Model-checks a Dogwood (.dw) policy file and reports, rule by rule, whether each one is " +
        "load-bearing. Three findings are possible and they are not stylistic: VACUOUS means a permit " +
        "never grants anything in any session -- that is zero control rather than weak control, and " +
        "nothing in the policy text says so, because it parses and it validates. REDUNDANT means a " +
        "permit fires but another permit always would too. DEAD means a forbid never denies anything " +
        "the rest of the set would have allowed. 'live' means the rule changes some verdict, and the " +
        "witness names the session that proves it.\n\n" +
        "THE BOUND IS REAL. VACUOUS means 'no session of up to `attempts` attempts makes it fire', not " +
        "'never'. Raise `attempts` to trade runtime for confidence, and report the bound alongside the " +
        "verdict rather than stating the verdict flatly.\n\n" +
        "PASS `eventSchema` WHENEVER ONE EXISTS. Without it, a policy written for AgentCore -- binding " +
        "`eventResource` -- is read under AgentCore's own schema (history per session), and any other " +
        "under Dogwood's own default reading -- callerPrincipal pinned, so a temporal condition sees " +
        "only the requesting principal's events -- which is right only if the deployment keeps that " +
        "default. If its schema has no universal pin, pass `pinned: false`. The tool echoes which " +
        "reading it used; do not drop that from your summary.\n\n" +
        "This runs TLC once per rule, so expect seconds to minutes, not milliseconds. It is not a " +
        "linter and it is not a retry-on-timeout call.\n\n" +
        "IF IT DOES NOT FINISH, use `smoke` rather than lowering `attempts`. See that argument.")]
    public async Task<PolicyCheckResult> CheckPolicyAsync(
        [Description("Path to the .dw policy file, relative to the project directory.")] string policy,
        [Description("Optional second .dw file -- the version being replaced. Given one, the tool stops checking rules and instead reports whether `policy` is MORE PERMISSIVE, LESS PERMISSIVE, EQUIVALENT or INCOMPARABLE to it, with a witness session for each direction. This is the question to ask about an EDIT. Report the direction, never just that they differ: a permission removed is a support ticket, a permission silently added is an incident.")] string? against = null,
        [Description("Path to the .dwschema event schema the policy is deployed under. Pass it whenever one exists; see the note above about the default reading.")] string? eventSchema = null,
        [Description(
            "The event-schema reading, when there is no `eventSchema` to pass. Omitted or `true` is " +
            "Dogwood's own default -- callerPrincipal pinned, so a temporal condition sees only the " +
            "requesting principal's events. `false` is the unpinned reading, global-trace semantics, " +
            "for a deployment whose schema has no universal pin. Refused together with " +
            "`eventSchema`: they are two answers to one question.")] bool? pinned = null,
        [Description("Path to a TLA+ module of your own that extends PolicyUnderTest and states what this policy is SUPPOSED to mean, with a companion .cfg naming its invariants. Use this for a claim the three built-in findings cannot express, such as 'SSH from the local range is permitted and every external source is denied', or any claim about TIMING, which the built-in questions cannot reach.\n\nPASS THE PATH AND NOTHING ELSE. You do not need to read the module first and you must not ask the user to paste it; this tool reads it. When an invariant is violated the reply quotes its definition back to you, which is what tells you WHICH DIRECTION failed -- a violated claim of the form `X => allowed` means the policy DENIED, and the name alone will not tell you that.")] string? property = null,
        [Description("Session length bound (default 3). This is the number that makes VACUOUS provisional.")] int? attempts = null,
        [Description("Numeric domain for input fields, 1..N (default 2).")] int? amount = null,
        [Description("Refuse a policy reading more than N input/output fields (default 4). The request space is the product of their domains, so this bounds the state space rather than soundness.")] int? maxFields = null,
        [Description(
            "Put the policy to the REFERENCE IMPLEMENTATION first (`dogwood check-parse`) and " +
            "stop if it will not parse.\n\n" +
            "WHAT THIS DISAMBIGUATES. This checker reads a SUBSET of Dogwood, so a refusal has " +
            "two possible meanings and one message: the construct is outside the subset, or the " +
            "policy is broken. Those need opposite responses -- one is a limitation to work " +
            "around, the other is a bug in the file to go and fix. The engine settles it, and " +
            "points at the token.\n\n" +
            "A syntax error is NOT a verification finding and must not be reported as one: the " +
            "policy has not been checked. The call exits 2, meaning no verdict. Costs about " +
            "35ms. When a refusal happens this is consulted anyway, so pass it when you want the " +
            "check FIRST -- on a policy a user has just edited, say.")] bool? syntax = null,
        [Description(
            "Before checking a `property`, say in ENGLISH what each of its claims forbids, which " +
            "states it will be checked in, and how many of those its condition even applies to. " +
            "Whether the property says what its author MEANT is the one question nothing " +
            "downstream verifies, and this is that question in a form a person can answer. A " +
            "claim reported as applying to NONE of its states will pass having tested nothing.")] bool? explain = null,
        [Description(
            "When a `property` claim comes back BROKEN, carry the counterexample back into " +
            "Dogwood: the concrete session it stands for as a .log trace, and the verdict the " +
            "real `dogwood replay` engine gives it.\n\n" +
            "USE THIS BEFORE REPORTING A BROKEN CLAIM TO A PERSON. The counterexample on its own " +
            "is a TLA+ variable -- `gap = 960` -- in units that are not written down, belonging " +
            "to a module they may not have written. This is the same finding in the language " +
            "their policy is written in, with a concrete value they can try, confirmed by the " +
            "reference implementation rather than by our model of it.")] bool? witness = null,
        [Description("Include the raw TLC output for each rule. Verbose and rarely what you want.")] bool? verbose = null,
        [Description(
            "Return the result as JSON with the witness as STRUCTURED EVENTS -- action, kind, time " +
            "and the input/output values -- instead of a one-line summary like 'Approve -> Trade'. " +
            "Only meaningful together with `against`.\n\n" +
            "Use this when you need to ACT on the witness rather than quote it: to say which input " +
            "reached the decision, to propose a fix, or to re-check after editing. The prose " +
            "summary names the actions and drops the values, so it cannot tell you that the session " +
            "that slipped through had port 22 rather than 3389.")] bool? trace = null,
        [Description(
            "Directory to keep the generated TLA+ in, instead of discarding it: the module built " +
            "from the policy text, the .cfg with the bounds, the raw TLC output, and a README " +
            "saying how to re-run it by hand.\n\n" +
            "For a reader who knows TLA+ and wants to check the model rather than take the verdict " +
            "on trust. Offer it when someone disputes a result. The path is resolved inside the " +
            "project directory and refused if it escapes.")] string? keep = null,
        [Description(
            "Run TLC as a random walk of N behaviours instead of exhaustively -- for a model too " +
            "big to exhaust, which is what raising `attempts` eventually produces. Try 1000.\n\n" +
            "READ THE RESULT DIFFERENTLY. A smoke run reports only `live` or `unknown`. `live` is " +
            "SOUND -- a witness is a witness however it was found, so the rule really does change " +
            "a verdict. `unknown` is NOT a finding: it means this random walk did not reach a " +
            "session where the rule matters, never that no such session exists. A smoke run can " +
            "never report VACUOUS, REDUNDANT or DEAD, because those are claims of ABSENCE and a " +
            "random walk cannot establish absence.\n\n" +
            "So: never summarise `unknown` as 'the rule is fine' or as 'the rule is inert', and " +
            "never suggest deleting a rule on the strength of it. Re-run without `smoke` for a " +
            "verdict, or raise N to search further.")] int? smoke = null,
        [Description("Seconds to allow before giving up (default 600).")] int? timeoutSeconds = null,
        CancellationToken cancellationToken = default)
    {
        var args = new List<string> { Resolve(policy, nameof(policy)) };

        Add(args, "--against", against, nameof(against));
        Add(args, "--event-schema", eventSchema, nameof(eventSchema));
        if (pinned is bool p) args.Add(p ? "--pinned" : "--unpinned");
        Add(args, "--property", property, nameof(property));

        if (attempts is int a) args.AddRange(["--attempts", a.ToString()]);
        if (amount is int m) args.AddRange(["--amount", m.ToString()]);
        if (maxFields is int f) args.AddRange(["--max-fields", f.ToString()]);
        if (smoke is int s) args.AddRange(["--smoke", s.ToString()]);
        if (verbose is true) args.Add("--verbose");
        if (syntax is true) args.Add("--syntax");
        if (explain is true) args.Add("--explain");
        if (witness is true) args.Add("--witness");

        // `--json` replaces the whole of stdout, the prose reading included, so the parsing below
        // must not also try to read findings out of it. `Findings` stays empty and the JSON is
        // carried in `Output` for the caller to parse -- which is what asked for it.
        if (trace is true) args.Add("--json");

        // Contained like every other path, but with the WRITE verb: this one is created, not read,
        // and an agent choosing where a tool writes is exactly the case containment exists for.
        if (!string.IsNullOrWhiteSpace(keep))
        {
            args.AddRange(["--keep", ProjectPath.Resolve(ProjectRoot, keep, nameof(keep), "Write")]);
        }

        var timeout = TimeSpan.FromSeconds(timeoutSeconds ?? 600);
        var r = await PythonProcess.RunAsync(CheckerScript, [.. args], root: AnchorRoot,
            timeout: timeout, ct: cancellationToken,
            // Only the progress lines: the rest of stderr is the refusal and error text, which is
            // reported with the result and would otherwise be printed twice.
            onError: Progress is null ? null : line =>
            {
                if (line.StartsWith("  TLC ", StringComparison.Ordinal) ||
                    line.StartsWith("        Progress", StringComparison.Ordinal))
                {
                    Progress(line);
                }
            },
            environment: Progress is null ? null : new Dictionary<string, string> { ["ANCHOR_PROGRESS"] = "1" });

        if (!r.IsSuccess)
        {
            // The checker could not be RUN. Distinct from a policy it declined to answer about, and
            // the distinction matters: one is our problem and the other is the policy's.
            return new PolicyCheckResult(false, null, [], "", r.Message ?? "the checker could not be run", null);
        }

        var run = r.Value;
        if (!Answered(run))
        {
            return new PolicyCheckResult(false, null, [], run.Output,
                Refusal(run.ErrorOutput) ?? $"the checker exited {run.ExitCode}: {run.ErrorOutput.Trim()}",
                run.ExitCode);
        }

        return new PolicyCheckResult(true, Reading(run.Output), [.. Findings(run.Output)], run.Output, null,
            run.ExitCode);
    }

    [McpServerTool(Name = "DescribePolicyModule")]
    [Description(
        "Describes what a custom TLA+ property module may name for one policy, and returns a " +
        "skeleton module that already runs. Use this BEFORE writing anything for `CheckPolicy`'s " +
        "`property` argument -- that argument asks you to write TLA+ against a module Anchor " +
        "GENERATES from the policy, and its vocabulary is derived from that policy's own text, so " +
        "it cannot be guessed.\n\n" +
        "The reply gives the action names, the input and output field names with each field's " +
        "domain, the pin keys, the rule list, and the tagged-value constructors. Values are " +
        "TAGGED: write `Num(22)`, never `22`, and an address is four octets via `Addr(a,b,c,d)` " +
        "because TLC works in Java ints and cannot hold one as a 32-bit number.\n\n" +
        "THE TRAP THIS EXISTS TO PREVENT. There is deliberately no `Inputs` set to quantify over. " +
        "A request space derived from the policy's own literals cannot test a claim about a value " +
        "the policy never mentions -- the value is absent from the vocabulary, so the claim ranges " +
        "over nothing and PASSES having examined nothing. State the requests your claim is about, " +
        "including values the policy never names. `plusOneValueThePolicyNeverNames` tells you the " +
        "model already admits one such value internally, but it is not writable.\n\n" +
        "Cheap: this parses only and runs no TLC, so it returns in well under a second. Unlike " +
        "CheckPolicy, it answers nothing about whether the policy is correct.")]
    public async Task<PolicyModuleDescription> DescribePolicyModuleAsync(
        [Description("Path to the .dw policy file, relative to the project directory.")] string policy,
        [Description("Path to the .dwschema event schema. It changes the vocabulary -- a universal pin adds partition keys -- so pass it whenever one exists.")] string? eventSchema = null,
        [Description("Numeric domain for input fields, 1..N (default 2). Widens the domains reported here.")] int? amount = null,
        [Description("Refuse a policy reading more than N input/output fields (default 4).")] int? maxFields = null,
        CancellationToken cancellationToken = default)
    {
        var args = new List<string> { Resolve(policy, nameof(policy)), "--describe" };

        Add(args, "--event-schema", eventSchema, nameof(eventSchema));
        if (amount is int m) args.AddRange(["--amount", m.ToString()]);
        if (maxFields is int f) args.AddRange(["--max-fields", f.ToString()]);

        // No TLC here, so a minute is already generous; a policy that takes longer than this to
        // PARSE is a bug rather than a big model.
        var r = await PythonProcess.RunAsync(CheckerScript, [.. args], root: AnchorRoot,
            timeout: TimeSpan.FromMinutes(1), ct: cancellationToken);

        if (!r.IsSuccess)
        {
            return new PolicyModuleDescription(false, null, r.Message ?? "the checker could not be run");
        }

        var run = r.Value;
        if (!Answered(run))
        {
            return new PolicyModuleDescription(false, null,
                Refusal(run.ErrorOutput) ?? $"the checker exited {run.ExitCode}: {run.ErrorOutput.Trim()}");
        }

        // Passed through rather than re-modelled in C#. The checker emits this document, so a field
        // added there reaches the agent without a second definition here to keep in step — the kind
        // of drift the rest of this project spends its tests preventing.
        try
        {
            return new PolicyModuleDescription(true, JsonSerializer.Deserialize<JsonElement>(run.Output), null);
        }
        catch (JsonException e)
        {
            return new PolicyModuleDescription(false, null,
                $"the checker's --describe output was not valid JSON: {e.Message}");
        }
    }

    [McpServerTool(Name = "CheckPropertyModule")]
    [Description(
        "Checks that a TLA+ property module COMPILES against a policy's generated vocabulary, and " +
        "stops there. SANY only, no model checking: about a second, against the minutes a full " +
        "`CheckPolicy` run costs.\n\n" +
        "USE THIS AFTER WRITING OR EDITING A MODULE, BEFORE CHECKING ANYTHING WITH IT. The " +
        "commonest thing wrong with a freshly written property module is that it does not compile " +
        "-- a misspelled operator, a name the policy's vocabulary does not have, an unbalanced " +
        "bracket -- and finding that out from a model-checking run means paying for the run first " +
        "and then reading the reason out of TLC's preamble. This gives you SANY's own message with " +
        "the line and column.\n\n" +
        "IT NEEDS THE POLICY, not just the module. A property module EXTENDS `PolicyUnderTest`, " +
        "which Anchor generates from the policy text, so 'does it compile' is only answerable " +
        "against a particular policy. A module that compiles here may still fail against a " +
        "different one.\n\n" +
        "A PASS SAYS NOTHING ABOUT THE POLICY. It says the module parses and resolves every name it " +
        "uses. Whether its claims hold is `CheckPolicy`; whether they say what you meant is " +
        "`ExplainPropertyModule`.")]
    public async Task<SpecCheckResult> CheckPropertyModuleAsync(
        [Description("Path to the .dw policy the module is written against, relative to the project directory.")] string policy,
        [Description("Path to the .tla property module to compile. Its companion .cfg is not read here -- compiling and being checked are different questions.")] string property,
        [Description("Path to the .dwschema event schema, if one exists. It changes the generated vocabulary, so a module can compile with it and not without.")] string? eventSchema = null,
        CancellationToken cancellationToken = default)
    {
        var args = new List<string>
        {
            Resolve(policy, nameof(policy)),
            "--property", Resolve(property, nameof(property)),
            "--parse",
        };
        Add(args, "--event-schema", eventSchema, nameof(eventSchema));

        // One JVM start and a parse. A minute is already generous, and a module that takes longer
        // than that to PARSE is a bug rather than a big model.
        var r = await PythonProcess.RunAsync(CheckerScript, [.. args], root: AnchorRoot,
            timeout: TimeSpan.FromMinutes(1), ct: cancellationToken);

        if (!r.IsSuccess)
        {
            return new SpecCheckResult(false, false, "", r.Message ?? "the checker could not be run");
        }

        var run = r.Value;
        var output = (run.Output + run.ErrorOutput).Trim();

        // 0 compiles, 2 does not. Anything else is the checker failing to answer -- a refused
        // policy, say -- which is neither of those and must not be reported as "does not compile":
        // the module might be perfect and the POLICY outside the modelled subset.
        return run.ExitCode switch
        {
            0 => new SpecCheckResult(true, true, output, null),
            2 when output.Contains("DOES NOT COMPILE")
                => new SpecCheckResult(true, false, output, null, Diagnostics(output)),
            _ => new SpecCheckResult(false, false, output,
                    Refusal(run.ErrorOutput) ?? $"the checker exited {run.ExitCode} without a verdict "
                                                + "about the module; the policy itself may be the problem"),
        };
    }

    [McpServerTool(Name = "ExplainPropertyModule")]
    [Description(
        "Says in ENGLISH what each claim in a TLA+ property module FORBIDS, which states it will be " +
        "checked in, and how many of those its condition even applies to. Reads the module; runs " +
        "nothing. Returns in milliseconds.\n\n" +
        "WHY THIS MATTERS MORE THAN IT SOUNDS. Everything downstream of a property is mechanical: " +
        "the checker either finds a counterexample or does not. Everything upstream is a person " +
        "saying what they meant. The step between -- whether the property says what they meant -- " +
        "is the one thing nothing else here verifies, and a property that says something ELSE is " +
        "checked just as rigorously and passes just as convincingly.\n\n" +
        "SO SHOW THE `forbids` LINE TO THE PERSON BEFORE RUNNING THE CHECK, and especially before " +
        "reporting that a claim holds. It is the only thing the claim can catch. If it does not " +
        "describe something they would object to seeing happen, the run will pass without having " +
        "tested their intention.\n\n" +
        "`vacuous` IS A FINDING AND MUST BE REPORTED AS ONE. It means no state the claim ranges " +
        "over can break it -- the condition is false everywhere, or the claim is true by the " +
        "module's own arithmetic. Such a claim HOLDS, the checker says so, and it examined nothing. " +
        "A green run containing one is worse than no run, because it reads as assurance.\n\n" +
        "`definedButNotChecked` lists claims the .cfg does not name. Those are not checked at all: " +
        "a property nobody listed is a property nobody checked.")]
    public async Task<SpecExplanation> ExplainPropertyModuleAsync(
        [Description("Path to the .tla property module, relative to the project directory.")] string property,
        [Description("Path to its .cfg, if it is not the module's own name. The .cfg decides which claims are checked at all, so it is read alongside rather than assumed.")] string? config = null,
        CancellationToken cancellationToken = default)
    {
        var args = new List<string> { Resolve(property, nameof(property)), "--json" };
        Add(args, "--cfg", config, nameof(config));

        var r = await PythonProcess.RunAsync(ExplainScript, [.. args], root: AnchorRoot,
            timeout: TimeSpan.FromMinutes(1), ct: cancellationToken);

        if (!r.IsSuccess)
        {
            return new SpecExplanation(false, null, r.Message ?? "the explainer could not be run");
        }

        var run = r.Value;

        // 0 and 4 both carry a full explanation -- 4 additionally means a claim cannot fail, which
        // is a finding about the module and is already in the document as `vacuous`. Treating it as
        // an error would throw away the explanation that says why.
        if (run.ExitCode is not (0 or 4))
        {
            return new SpecExplanation(false, null,
                $"the explainer exited {run.ExitCode}: {run.ErrorOutput.Trim()}");
        }

        try
        {
            return new SpecExplanation(true, JsonSerializer.Deserialize<JsonElement>(run.Output), null);
        }
        catch (JsonException e)
        {
            return new SpecExplanation(false, null, $"the explainer's output was not valid JSON: {e.Message}");
        }
    }

    [McpServerTool(Name = "EvaluateExpression")]
    [Description(
        "Evaluates a TLA+ expression in a policy's own semantics and returns the VALUE. Seconds. " +
        "It checks nothing.\n\n" +
        "THIS IS THE TOOL FOR A QUESTION RATHER THAN A CLAIM. `CheckPolicy` answers \"does this " +
        "hold in every state\"; this answers \"what IS this\" -- and most of what goes wrong while " +
        "writing a property module is a value being something other than you assumed. The units " +
        "of a window, what a session actually contains, whether a set has the member you think. " +
        "Asking directly costs seconds; finding out by writing an invariant and running a check " +
        "costs minutes and tells you only that something was wrong.\n\n" +
        "WITH `property`, THAT MODULE'S DEFINITIONS ARE IN SCOPE, which is where this earns its " +
        "keep. `Session(960)` returns the events with their times. `TradeAllowed(960)` returns " +
        "TRUE or FALSE -- the policy's decision for that session, without an invariant anywhere. " +
        "A tuple evaluates in one call, so `<<TradeAllowed(900), TradeAllowed(901)>>` locates the " +
        "boundary of a temporal window in a single question.\n\n" +
        "WITHOUT IT, the policy's generated vocabulary is the context: `Policies`, the field " +
        "domains, the tagged constructors.\n\n" +
        "A VALUE IS NOT A VERDICT. That the policy grants one session says nothing about the " +
        "others, and reporting an evaluation as if it were a check would be claiming far more " +
        "than was established. Use it to understand, then check.")]
    public async Task<ExpressionValue> EvaluateExpressionAsync(
        [Description("Path to the .dw policy whose semantics the expression is evaluated in, relative to the project directory.")] string policy,
        [Description("The TLA+ expression. Anything the context defines: `Session(960)`, `TradeAllowed(960)`, `Len(Policies)`, `<<A, B>>` to ask two things at once.")] string expression,
        [Description("Optional .tla property module to evaluate inside, so ITS definitions are in scope too. Without it only the generated vocabulary is.")] string? property = null,
        [Description("Path to the .dwschema event schema, if one exists. It changes the generated vocabulary and so can change the value.")] string? eventSchema = null,
        CancellationToken cancellationToken = default)
    {
        var args = new List<string> { Resolve(policy, nameof(policy)), "--eval", expression };

        Add(args, "--property", property, nameof(property));
        Add(args, "--event-schema", eventSchema, nameof(eventSchema));

        // One TLC start and one evaluation, not a model check. Generous against a cold JVM.
        var r = await PythonProcess.RunAsync(CheckerScript, [.. args], root: AnchorRoot,
            timeout: TimeSpan.FromMinutes(5), ct: cancellationToken);

        if (!r.IsSuccess)
        {
            return new ExpressionValue(false, null, r.Message ?? "the checker could not be run");
        }

        var run = r.Value;
        var output = (run.Output + run.ErrorOutput).Trim();

        if (run.ExitCode != 0)
        {
            // The expression did not evaluate -- a name the context does not define, a cross-kind
            // comparison, a value TLC will not print. The output carries TLC's reason and is
            // returned whole: an unreadable answer beats a confident empty one.
            return new ExpressionValue(false, null,
                Refusal(run.ErrorOutput) ?? $"the expression did not evaluate:\n{output}");
        }

        return new ExpressionValue(true, Evaluated(output), null);
    }

    /// <summary>The value out of the checker's `--eval` report, without its echo of the question.</summary>
    /// <remarks>
    /// The report prints the expression, a blank line, and then the value indented. Everything from
    /// the first indented line on is the value — kept as text rather than parsed into a structure,
    /// because a TLA+ value is a record, a set, a sequence or a scalar and flattening those into one
    /// shape would lose the distinction the reader is asking about.
    /// </remarks>
    public static string Evaluated(string output)
    {
        var lines = output.Split('\n').Select(l => l.TrimEnd('\r')).ToArray();
        // Not `l[6..]` unguarded: a value ends with a trailing blank line more often than not, and
        // slicing a shorter line than the indent throws — turning "here is the value" into an
        // exception, which is the worst possible way to report a successful evaluation.
        var value = lines.SkipWhile(l => !l.StartsWith("      "))
                         .Select(l => l.Length >= 6 ? l[6..] : l.TrimStart());
        return string.Join("\n", value).Trim();
    }

    /// <summary>Each error SANY reported, with where it is.</summary>
    /// <remarks>
    /// <para>
    /// Parsed from the printed output rather than from a machine format, for the same reason
    /// <see cref="Findings"/> is: the CLI is the contract we already have, and inventing a second
    /// one would be a second thing to keep true. Anything unparsed is simply absent from the list
    /// and <see cref="SpecCheckResult.Output"/> is returned whole alongside, so a changed format
    /// degrades to "fewer structured diagnostics" rather than to a wrong answer.
    /// </para>
    /// <para>
    /// SANY writes a location line and then the message after a blank line:
    /// </para>
    /// <code>
    /// line 47, col 58 to line 47, col 62 of module typo
    ///
    /// Unknown operator: `Grant'.
    /// </code>
    /// <para>
    /// An abort — an unparseable module — carries no location at all, only
    /// <c>Could not parse module X from file X.tla</c>. Those are returned with line 0 rather than
    /// dropped: a module that will not parse is the case an agent most needs told about.
    /// </para>
    /// </remarks>
    public static IReadOnlyList<SpecDiagnostic> Diagnostics(string output)
    {
        var found = new List<SpecDiagnostic>();
        var lines = output.Split('\n').Select(l => l.TrimEnd('\r')).ToArray();

        for (var i = 0; i < lines.Length; i++)
        {
            var at = SanyLocation().Match(lines[i]);
            if (at.Success)
            {
                // The message is the next non-blank line. SANY separates them with one blank line,
                // but reading "the next non-blank" survives a second one being added.
                var message = lines.Skip(i + 1).FirstOrDefault(l => l.Trim().Length > 0)?.Trim() ?? "";
                found.Add(new SpecDiagnostic(
                    int.Parse(at.Groups["line"].Value),
                    int.Parse(at.Groups["col"].Value),
                    at.Groups["module"].Value,
                    message));
                continue;
            }

            var abort = SanyAbort().Match(lines[i]);
            if (abort.Success)
            {
                found.Add(new SpecDiagnostic(0, 0, abort.Groups["module"].Value, lines[i].Trim()));
            }
        }

        return found;
    }

    /// <summary>The rule-by-rule findings in the checker's output.</summary>
    /// <remarks>
    /// Parsed from the printed table rather than from a machine format, because the checker's CLI is
    /// the contract we already have and inventing a second one would be a second thing to keep true.
    /// Anything unparsed is simply absent from the list — <see cref="PolicyCheckResult.Output"/> is
    /// returned whole alongside it, so a changed format degrades to "fewer structured findings"
    /// rather than to a wrong answer.
    /// </remarks>
    public static IEnumerable<RuleFinding> Findings(string output) =>
        FindingLine().Matches(output).Select(m => new RuleFinding(
            int.Parse(m.Groups["rule"].Value),
            m.Groups["effect"].Value,
            m.Groups["verdict"].Value,
            m.Groups["note"].Value.Trim()));

    /// <summary>
    /// Which reading produced the answers — the line the checker prints before anything else.
    /// </summary>
    /// <remarks>
    /// Kept as its own field because it is the single most droppable part of the output and the most
    /// expensive to drop: a verdict computed under one reading, reported without it, reads as a
    /// verdict about whatever deployment the reader has in mind.
    /// </remarks>
    public static string? Reading(string output)
    {
        var text = output.Replace("\r\n", "\n");
        var match = ReadingLine().Match(text);
        if (match.Success)
        {
            return match.Value.Trim();
        }
        // Chosen for the caller, because the policy binds AgentCore's scope fields.
        if (text.Contains("uses\n  AgentCore's event schema"))
        {
            return "the policy binds eventResource/eventPrincipal, so every answer uses AgentCore's event " +
                   "schema: history partitioned by session, one gateway in the model. Not modelled: AgentCore " +
                   "records a response 'shortly after' completion, where the model has it recorded before " +
                   "the next request";
        }
        // The default, which the checker words as a default so nobody mistakes it for a choice.
        return text.Contains("uses Dogwood's own default")
            ? "no event schema given, so every answer uses Dogwood's own default reading: callerPrincipal " +
              "pinned, so a temporal condition sees only the requesting principal's events. Right only if " +
              "the deployment keeps that default; pass eventSchema for its real one, or pinned: false if " +
              "it has no universal pin"
            : null;
    }

    /// <summary>Did the checker reach a verdict, whatever the verdict was?</summary>
    /// <remarks>
    /// The checker's exit code says whether it ANSWERED, not whether the answer was good news:
    /// <list type="bullet">
    /// <item><c>0</c> — answered. Covers findings: a VACUOUS permit, a DEAD forbid, two policies
    /// that differ. A finding is not an error.</item>
    /// <item><c>1</c> — answered, and a <c>--property</c> claim is BROKEN. The most useful answer
    /// the tool can give, and the reason this is not "nonzero means failure": treating it as a
    /// failure reports a policy that provably violates its own stated meaning as a tool that would
    /// not run.</item>
    /// <item><c>2</c> — did NOT answer. The file is missing, or the policy is outside the modelled
    /// subset and the checker refused rather than approximating.</item>
    /// </list>
    /// </remarks>
    static bool Answered(PythonRun run) => run.ExitCode != DidNotAnswer;

    static string? Refusal(string stderr)
    {
        var text = stderr.Replace("\r\n", "\n").Trim();
        return text.StartsWith("REFUSED:") || text.StartsWith("no such policy file:") ? text : null;
    }

    void Add(List<string> args, string flag, string? path, string parameter)
    {
        if (!string.IsNullOrWhiteSpace(path))
        {
            args.AddRange([flag, Resolve(path, parameter)]);
        }
    }

    /// <summary>
    /// A path as the agent wrote it, resolved inside the project. Containment applies to reads:
    /// a checker that will read any file on the host is a file-disclosure tool wearing a verifier's
    /// name, since the policy text comes back in the output.
    /// </summary>
    string Resolve(string path, string parameter) =>
        ProjectPath.Resolve(ProjectRoot, path, parameter, "Read");

    // "  permit #1  action == Connect       live      witness: Connect"
    // Anchored on the verdict word rather than on column positions: the label is padded to 34 and a
    // longer one simply runs into the verdict with no separator at all.
    [GeneratedRegex(@"^[ \t]+(?<effect>permit|forbid)[ \t]+#(?<rule>\d+)[ \t]+action == .+?[ \t]+(?<verdict>VACUOUS|REDUNDANT|DEAD|unknown|live)\b(?<note>.*)$",
        RegexOptions.Multiline)]
    private static partial Regex FindingLine();

    [GeneratedRegex(@"^under .+$", RegexOptions.Multiline)]
    private static partial Regex ReadingLine();

    [GeneratedRegex(@"^line (?<line>\d+), col (?<col>\d+) to line \d+, col \d+ of module (?<module>\S+)")]
    private static partial Regex SanyLocation();

    [GeneratedRegex(@"Could not parse module (?<module>\S+)")]
    private static partial Regex SanyAbort();

    #endregion

    #region Fields

    /// <summary>Relative to the Anchor root, which is where <see cref="PythonProcess"/> runs it.</summary>
    public const string CheckerScript = "src/checker/properties.py";

    /// <summary>The unattended directory check. Relative to the Anchor root, like the checker.</summary>
    public const string AuditScript = "src/agent/audit.py";

    /// <summary>The property explainer, which runs no model checker. Relative to the Anchor root.</summary>
    public const string ExplainScript = "src/checker/explain.py";

    /// <summary>The one exit code that means no verdict was reached. See <c>Answered</c>.</summary>
    public const int DidNotAnswer = 2;

    #endregion
}

/// <summary>One rule's verdict. <paramref name="Verdict"/> is VACUOUS, REDUNDANT, DEAD or live.</summary>
public record RuleFinding(int Rule, string Effect, string Verdict, string Note);

/// <summary>
/// What the checker said. <paramref name="Answered"/> false means no verdict was produced — either
/// the checker could not run or it refused the policy — and <paramref name="Error"/> says which.
/// </summary>
public record PolicyCheckResult(
    bool Answered,
    string? Reading,
    IReadOnlyList<RuleFinding> Findings,
    string Output,
    string? Error,
    int? ExitCode = null)
{
    /// <summary>
    /// A <c>property</c> claim was checked and is VIOLATED. The most useful answer the checker
    /// gives, so it is carried rather than left to be read back out of the text. A null
    /// <paramref name="ExitCode"/> means the checker never ran at all.
    /// </summary>
    public bool PropertyBroken => ExitCode == 1;

    /// <summary>Rules that are not load-bearing. Empty on a policy where every rule matters.</summary>
    public IEnumerable<RuleFinding> Inert =>
        Findings.Where(f => f.Verdict is not ("live" or "unknown"));

    /// <summary>
    /// Rules a smoke run could not settle. NOT findings: `unknown` means the random walk did not
    /// reach a session where the rule matters, never that no such session exists. Reporting these
    /// as deletable would be advice to delete a working rule.
    /// </summary>
    public IEnumerable<RuleFinding> Unsettled => Findings.Where(f => f.Verdict == "unknown");
}

/// <summary>
/// What a property module may name for one policy. <paramref name="Module"/> is the checker's own
/// <c>--describe</c> document, passed through verbatim.
/// </summary>
public record PolicyModuleDescription(bool Answered, JsonElement? Module, string? Error);

/// <summary>
/// Whether a property module compiles. <paramref name="Answered"/> false means no verdict was
/// reached at all — the checker could not run, or the POLICY was refused — which is neither
/// "compiles" nor "does not".
/// </summary>
public record SpecCheckResult(
    bool Answered,
    bool Compiles,
    string Output,
    string? Error,
    IReadOnlyList<SpecDiagnostic>? Diagnostics = null);

/// <summary>
/// One error SANY reported. <paramref name="Line"/> 0 means it gave no location — an unparseable
/// module, where there is no well-formed position to point at.
/// </summary>
public record SpecDiagnostic(int Line, int Column, string Module, string Message);

/// <summary>
/// What a TLA+ expression evaluates to. <paramref name="Value"/> is TLA+ value syntax, kept as
/// text: a record, a set, a sequence and a scalar are different shapes and flattening them would
/// lose the distinction being asked about.
/// </summary>
public record ExpressionValue(bool Answered, string? Value, string? Error);

/// <summary>
/// What each claim in a property module forbids. <paramref name="Explanation"/> is the explainer's
/// own document, passed through verbatim so a field added there reaches the agent without a second
/// definition here to keep in step.
/// </summary>
public record SpecExplanation(bool Answered, JsonElement? Explanation, string? Error);
