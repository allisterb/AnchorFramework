namespace Anchor.CLI;

using CommandLine;

/// <summary>Flags every verb accepts.</summary>
public class Options
{
    #region Properties

    [Option("debug", Required = false, HelpText = "Debug-level logging, and to the console as well as the log file.")]
    public bool Debug { get; set; }

    [Option("anchor-root", Required = false,
        HelpText = "The Anchor tree the Python checker runs from. Defaults to $ANCHOR_ROOT, then the enclosing checkout.")]
    public string AnchorRoot { get; set; } = string.Empty;

    [Option("project-dir", Required = false,
        HelpText = "The directory paths are resolved inside; a path escaping it is refused. WITHOUT IT " +
                   "THERE IS NO CONTAINMENT — any path the caller names is read as given. Pass it when serving an agent.")]
    public string ProjectDir { get; set; } = string.Empty;

    #endregion
}

/// <summary>Model-check a Dogwood policy set.</summary>
[Verb("check", HelpText =
    "Model-check a Dogwood policy set (a .dw file of one or more permit/forbid policies, called " +
    "rules here).\n" +
    "check <policy-set.dw>: rule by rule, does each rule change a verdict of the set, or is it " +
    "VACUOUS, REDUNDANT or DEAD? Prints the verdicts, writes nothing, asks no LLM, and lists the " +
    "property modules and questions --full would use. Runs TLC once per rule: seconds.\n" +
    "check <directory>: the same, for every .dw in it.\n" +
    "check <policy-set.dw | directory> --full: an audit. Also checks every .tla property module " +
    "whose header names a policy set, and asks the questions in questions.md of an LLM (--no-llm " +
    "skips them), after scanning the inputs for hidden text and instructions aimed at an LLM. " +
    "Writes findings.md, findings.html, results.json and traces/ into the directory, or into " +
    "<policy-set>-findings/ beside a single policy set file. The LLM is optional: one that cannot " +
    "be reached is a warning and the questions are skipped, unless --llm, --provider or --config " +
    "asked for it, which makes it required and tests it with a one-token request before the run.\n" +
    "Exit codes: \n" +
    "0: answered or nothing to look at.\n1: a --property claim is BROKEN or there are findings.\n2: no verdict.\n3: could not run.")]
public class CheckOptions : Options
{
    #region Properties

    /// <summary>
    /// A .dw file, or a DIRECTORY of them. Either is checked rule by rule and printed; with --full,
    /// either is audited and written up. One flag, one meaning, whichever the shape.
    /// </summary>
    /// <remarks>
    /// This used to be a separate <c>auto</c> verb, and that name claimed the wrong thing — "auto"
    /// means autoformalization in this field, and nothing there formalizes anything: every
    /// intentional claim it checks is a <c>.tla</c> a person wrote. Branching on the argument
    /// rather than on a flag follows <c>pipeline.sweep()</c>, which already reads a path both ways.
    /// </remarks>
    [Value(0, MetaName = "policy-set-or-directory", Required = true,
        HelpText = "A .dw policy set file, or a directory of them.")]
    public string Policy { get; set; } = string.Empty;

    // --- what is checked, in both modes ------------------------------------------------------

    [Option("full", Required = false,
        HelpText = "Audit rather than check: also run every property module whose header names a " +
                   "policy set, ask the questions in questions.md of an LLM, and write the report. " +
                   "The same for a policy set file and a directory.")]
    public bool Full { get; set; }

    [Option("property", Required = false, MetaValue = "FILE.tla",
        HelpText = "POLICY SET FILE ONLY. Your own claim about what the policy set means, as a TLA+ module " +
                   "extending PolicyUnderTest, with a companion .cfg naming its invariants. Without " +
                   "--full it is checked and printed; with --full it is checked as well as the modules " +
                   "whose header names the policy set, and marked in the report as given.")]
    public string Property { get; set; } = string.Empty;

    [Option("event-schema", Required = false, MetaValue = "FILE.dwschema",
        HelpText = "The .dwschema the policy set is deployed under. Without one, a policy binding " +
                   "eventResource or eventPrincipal is read under AgentCore's own schema (history per " +
                   "session), and any other under Dogwood's default: callerPrincipal pinned, so a " +
                   "temporal condition sees only the requesting principal's earlier events. Pass the " +
                   "real schema if you have one, or --unpinned if yours has no universal pin.")]
    public string EventSchema { get; set; } = string.Empty;

    [Option("pinned", Required = false,
        HelpText = "Dogwood's own default reading, and Anchor's, stated explicitly: callerPrincipal " +
                   "pinned, so a temporal condition sees only the requesting principal's events. Not " +
                   "with --event-schema or --unpinned.")]
    public bool Pinned { get; set; }

    [Option("unpinned", Required = false,
        HelpText = "No pins, so a temporal condition sees every principal's events in the session. For " +
                   "a deployment whose event schema has no universal pin. Not with --event-schema or " +
                   "--pinned.")]
    public bool Unpinned { get; set; }

    // --- the audit's report and its LLM: --full only ------------------------------------------
    // Each is refused with a message when --full is absent, rather than ignored: an option that
    // silently does nothing is worse than one that is not there.

    [Option("output-dir", Required = false, MetaValue = "DIR",
        HelpText = "--full ONLY. Where to write findings.md, findings.html, results.json and traces/ " +
                   "(default: the directory itself, or <policy-set>-findings/ beside a single policy " +
                   "set file, so it never overwrites the directory's report).")]
    public string OutputDir { get; set; } = string.Empty;

    [Option("no-llm", Required = false,
        HelpText = "--full ONLY. Run the checks and write the report without asking an LLM " +
                   "anything. Most of the value, none of the cost, and the part that belongs in CI.")]
    public bool NoLlm { get; set; }

    [Option("provider", Required = false, MetaValue = "NAME",
        HelpText = "--full ONLY. Which service's LLM answers questions.md: gemini, bedrock, or auto " +
                   "(the default), which picks gemini when a Gemini API key is configured and bedrock " +
                   "otherwise. Credentials are read from the environment first -- GEMINI_API_KEY or " +
                   "GOOGLE_API_KEY; AWS_BEARER_TOKEN_BEDROCK or ordinary AWS credentials, and " +
                   "AWS_REGION -- then from the settings file: see --config. Given at all, it makes the " +
                   "LLM required: `--provider auto` is how to say \"use the LLM I have configured, " +
                   "and stop before the run if it cannot be reached\".")]
    public string Provider { get; set; } = string.Empty;

    [Option("llm", Required = false, MetaValue = "MODEL-ID",
        HelpText = "--full ONLY. Which model the provider runs, by its id: gemini-2.5-flash, or a " +
                   "Bedrock model id your account has enabled. Default: the provider's Model setting " +
                   "(Gemini:Model or Bedrock:Model, see --config), then gemini-2.5-flash for gemini " +
                   "or the Strands SDK's own for bedrock. Not needed to use an LLM -- --full already " +
                   "asks one whenever there is a questions.md, unless --no-llm is given.")]
    public string Llm { get; set; } = string.Empty;

    [Option("config", Required = false, MetaValue = "APPSETTINGS.JSON",
        HelpText = "--full ONLY. The settings file holding the LLM's API key, model and provider settings; " +
                   "see src/agent/appsettings.json.example. Without it: the file $ANCHOR_APPSETTINGS " +
                   "names, else src/agent/appsettings.json, else appsettings.json at the Anchor root -- " +
                   "never one in your directory. In a container, how a mounted file is named. A path " +
                   "that is not there is refused.")]
    public string Config { get; set; } = string.Empty;

    [Option("allow-flagged-input", Required = false,
        HelpText = "--full ONLY. Ask the LLM its questions even when the input scan found " +
                   "high-severity text in the inputs — hidden characters, instructions aimed at " +
                   "an LLM, markup. For findings you have read and judged benign; the report " +
                   "records that it was used. The checks themselves always run.")]
    public bool AllowFlaggedInput { get; set; }

    // --- one policy set, without --full ---------------------------------------------------------

    [Option("against", Required = false, MetaValue = "OTHER.dw",
        HelpText = "POLICY SET FILE, WITHOUT --full. A second .dw file: the policy set this one replaces. Reports whether this policy set is " +
                   "MORE PERMISSIVE, LESS PERMISSIVE, EQUIVALENT or INCOMPARABLE to it, with a " +
                   "witness session for each direction, instead of checking each rule. The question " +
                   "to ask before replacing a policy set: a permission removed is a support ticket, a " +
                   "permission silently added is an incident.")]
    public string Against { get; set; } = string.Empty;

    [Option("explain", Required = false,
        HelpText = "POLICY SET FILE, WITHOUT --full. Before checking a --property, say in English what each claim FORBIDS and how " +
                   "many of the states it ranges over its condition applies to. Same reading as " +
                   "the `explain` verb, printed before the verdict instead of after it.")]
    public bool Explain { get; set; }

    [Option("witness", Required = false,
        HelpText = "POLICY SET FILE, WITHOUT --full (which always does this). When a --property claim is BROKEN, carry the counterexample back into Dogwood " +
                   "— the session it stands for as a .log trace, and the verdict `dogwood replay` " +
                   "gives it. The finding in the language the policy was written in, confirmed by " +
                   "the reference engine. Needs the dogwood binary; says so when it is absent.")]
    public bool Witness { get; set; }

    [Option("trace", Required = false,
        HelpText = "POLICY SET FILE, WITHOUT --full. Emit the result as JSON with the witness as structured EVENTS — action, kind, " +
                   "time and the input/output values — instead of a one-line summary. For anything " +
                   "that has to act on the answer rather than read it. Use with --against.")]
    public bool Trace { get; set; }

    [Option("keep", Required = false, MetaValue = "DIR",
        HelpText = "POLICY SET FILE, WITHOUT --full (which always keeps traces/). Keep the generated TLA+ here instead of discarding it: the module built from " +
                   "the policy text, the .cfg with the bounds, the raw TLC output, and a README " +
                   "saying how to re-run it. For checking the model rather than trusting the verdict.")]
    public string Keep { get; set; } = string.Empty;

    [Option("syntax", Required = false,
        HelpText = "WITHOUT --full. Put the policy set to the reference implementation (`dogwood check-parse`) before " +
                   "checking anything, and stop if it will not parse — pointing at the token. A " +
                   "syntax error is not a verification finding, but it is why a run produces none. " +
                   "Exits 2 (no verdict). ~35ms; skipped with a note when the binary is not built.")]
    public bool Syntax { get; set; }

    // --- bounds and tuning ------------------------------------------------------------------------

    [Option("attempts", Required = false,
        HelpText = "Attempts per session: every session of up to this many attempts is checked (default 3). " +
                   "Each attempt multiplies the sessions to search, so a large policy set may need --smoke. " +
                   "This is the number that makes a VACUOUS verdict provisional.")]
    public int? Attempts { get; set; }

    /// <summary>
    /// Takes a number rather than being a bare switch with a default. CommandLineParser has no
    /// optional-value option, and faking one by rewriting argv before parsing is the hand-rolled
    /// parsing this file exists to remove. 1000 is the number to reach for.
    /// </summary>
    [Option("smoke", Required = false, MetaValue = "N",
        HelpText = "Random walk of N behaviours instead of exhaustive search; try 1000. Reports only " +
                   "`live` or `unknown`, never VACUOUS/REDUNDANT/DEAD — those are claims of absence, " +
                   "which a random walk cannot establish.")]
    public int? Smoke { get; set; }

    [Option("max-fields", Required = false,
        HelpText = "Refuse a policy set reading more than N input/output fields (default 4). The request " +
                   "space is the product of their domains.")]
    public int? MaxFields { get; set; }

    [Option("amount", Required = false,
        HelpText = "WITHOUT --full. Numeric domain for input fields, 1..N (default 2).")]
    public int? Amount { get; set; }

    [Option("verbose", Required = false,
        HelpText = "WITHOUT --full. Include the raw TLC output for each rule.")]
    public bool Verbose { get; set; }

    [Option("timeout", Required = false,
        HelpText = "WITHOUT --full. Seconds before giving up on each policy set (default 600).")]
    public int? Timeout { get; set; }
    #endregion
}

/// <summary>Say in English what a property module forbids, before anything is checked.</summary>
/// <remarks>
/// Its own verb rather than a flag on <c>check</c> because it is used at a different moment and by
/// a different person. <c>check</c> answers "is this policy set what the property says"; this answers
/// "is the property what I meant", which is the one question in the pipeline nothing downstream
/// verifies — and the moment to ask it is before a run, when disagreeing is still free.
/// </remarks>
[Verb("explain", HelpText =
    "Read a property module and say, per claim, what it FORBIDS, which states it will be checked " +
    "in, and how many of those its condition even applies to. Runs no model checker. Exit 4 when " +
    "a claim cannot fail — it would pass having tested nothing.")]
public class ExplainOptions : Options
{
    #region Properties

    [Value(0, MetaName = "module", Required = true, HelpText = "A property module (.tla).")]
    public string Module { get; set; } = string.Empty;

    [Option("cfg", Required = false, MetaValue = "FILE.cfg",
        HelpText = "Its .cfg fie, if different to the module's own name. The .cfg is what decides which claims " +
                   "are checked at all, so it is read alongside rather than assumed.")]
    public string Config { get; set; } = string.Empty;

    [Option("json", Required = false,
        HelpText = "Emit the explanation as JSON — the claims, what each forbids, and the states " +
                   "its condition applies to. For an agent, or a report generator.")]
    public bool Json { get; set; }

    #endregion
}

/// <summary>
/// Start the MCP server. The default verb, because that is how an MCP host launches this binary.
/// </summary>
/// <remarks>
/// Default in the <c>CommandLineParser</c> sense — a host invoking <c>anchor server</c> gets here,
/// and so would a host passing only flags. A completely bare invocation is turned into
/// <c>--help</c> by <c>Program</c>; see the note there for why.
/// </remarks>
[Verb("server", isDefault: true, HelpText = "Start the Anchor MCP server in stdio or HTTP mode.")]
public class ServerOptions : Options
{
    #region Properties

    [Option("http", Required = false, HelpText = "Serve over HTTP instead of the default stdio.")]
    public bool Http { get; set; }

    [Option("port", Required = false, HelpText = "HTTP listening port (default: 8080).")]
    public int? Port { get; set; }

    #endregion
}