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
    "rules here) rule by rule: does each one change a verdict of the set, or is it VACUOUS, " +
    "REDUNDANT or DEAD? Runs TLC once per rule, so can take seconds to complete. Given a directory path " +
    "it will audit every .dw in it, pairing each with every .tla property module whose header names it, and " +
    "writes findings.md, findings.html, results.json and traces/ beside them, after scanning " +
    "the inputs for hidden text and instructions aimed at an LLM. Exit codes: \n" +
    "0: answered or nothing to look at.\n1: a --property claim is BROKEN or there are findings.\n2: no verdict.\n3: could not run.")]
public class CheckOptions : Options
{
    #region Properties

    /// <summary>
    /// A .dw file, or a DIRECTORY of them. The shape decides which run happens, rather than a flag:
    /// one policy set is checked rule by rule and printed; a directory is audited and written up.
    /// </summary>
    /// <remarks>
    /// This used to be a separate <c>auto</c> verb, and that name claimed the wrong thing — "auto"
    /// means autoformalization in this field, and nothing there formalizes anything: every
    /// intentional claim it checks is a <c>.tla</c> a person wrote. Branching on the argument
    /// rather than on a flag follows <c>pipeline.sweep()</c>, which already reads a path both ways.
    /// </remarks>
    [Value(0, MetaName = "policy-set-or-directory", Required = true,
        HelpText = "A .dw policy set, or a directory of them to audit.")]
    public string Policy { get; set; } = string.Empty;

    [Option("against", Required = false, MetaValue = "OTHER.dw",
        HelpText = "A second .dw file: the policy set this one replaces. Reports whether this policy set is " +
                   "MORE PERMISSIVE, LESS PERMISSIVE, EQUIVALENT or INCOMPARABLE to it, with a " +
                   "witness session for each direction, instead of checking each rule. The question " +
                   "to ask before replacing a policy set: a permission removed is a support ticket, a " +
                   "permission silently added is an incident.")]
    public string Against { get; set; } = string.Empty;

    [Option("event-schema", Required = false, MetaValue = "FILE.dwschema",
        HelpText = "The .dwschema the policy set is deployed under. PASS IT IF YOU HAVE ONE: without it " +
                   "every answer assumes the unpinned reading, which is not the shipped default.")]
    public string EventSchema { get; set; } = string.Empty;

    [Option("property", Required = false, MetaValue = "FILE.tla",
        HelpText = "Your own claim about what the policy set means, as a TLA+ module extending " +
                   "PolicyUnderTest, with a companion .cfg naming its invariants.")]
    public string Property { get; set; } = string.Empty;

    [Option("attempts", Required = false,
        HelpText = "Session length bound (default 3). This is the number that makes a VACUOUS verdict provisional.")]
    public int? Attempts { get; set; }

    [Option("amount", Required = false, HelpText = "Numeric domain for input fields, 1..N (default 2).")]
    public int? Amount { get; set; }

    [Option("max-fields", Required = false,
        HelpText = "Refuse a policy set reading more than N input/output fields (default 4). The request " +
                   "space is the product of their domains.")]
    public int? MaxFields { get; set; }

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

    [Option("verbose", Required = false, HelpText = "Include the raw TLC output for each rule.")]
    public bool Verbose { get; set; }

    // --- a DIRECTORY only -----------------------------------------------------------------------
    // Refused with a message when the argument is a single policy set, rather than ignored: an option
    // that silently does nothing is worse than one that is not there.

    [Option("output-dir", Required = false, MetaValue = "DIR",
        HelpText = "DIRECTORY ONLY. Where to write findings.md, findings.html, results.json and traces/ " +
                   "(default: the directory itself).")]
    public string OutputDir { get; set; } = string.Empty;

    [Option("no-llm", Required = false,
        HelpText = "DIRECTORY ONLY. Run the checks and write the report without asking an LLM " +
                   "anything. Most of the value, none of the cost, and the part that belongs in CI.")]
    public bool NoLlm { get; set; }

    [Option("allow-flagged-input", Required = false,
        HelpText = "DIRECTORY ONLY. Ask the LLM its questions even when the input scan found " +
                   "high-severity text in the inputs — hidden characters, instructions aimed at " +
                   "an LLM, markup. For findings you have read and judged benign; the report " +
                   "records that it was used. The checks themselves always run.")]
    public bool AllowFlaggedInput { get; set; }

    [Option("provider", Required = false, HelpText = "DIRECTORY ONLY. auto, bedrock or gemini.")]
    public string Provider { get; set; } = string.Empty;

    [Option("llm", Required = false,
        HelpText = "DIRECTORY ONLY. The LLM's model id; defaults to the provider's own.")]
    public string Llm { get; set; } = string.Empty;

    [Option("syntax", Required = false,
        HelpText = "Put the policy set to the reference implementation (`dogwood check-parse`) before " +
                   "checking anything, and stop if it will not parse — pointing at the token. A " +
                   "syntax error is not a verification finding, but it is why a run produces none. " +
                   "Exits 2 (no verdict). ~35ms; skipped with a note when the binary is not built.")]
    public bool Syntax { get; set; }

    [Option("explain", Required = false,
        HelpText = "Before checking a --property, say in English what each claim FORBIDS and how " +
                   "many of the states it ranges over its condition applies to. Same reading as " +
                   "the `explain` verb, printed before the verdict instead of after it.")]
    public bool Explain { get; set; }

    [Option("witness", Required = false,
        HelpText = "When a --property claim is BROKEN, carry the counterexample back into Dogwood " +
                   "— the session it stands for as a .log trace, and the verdict `dogwood replay` " +
                   "gives it. The finding in the language the policy was written in, confirmed by " +
                   "the reference engine. Needs the dogwood binary; says so when it is absent.")]
    public bool Witness { get; set; }

    [Option("trace", Required = false,
        HelpText = "Emit the result as JSON with the witness as structured EVENTS — action, kind, " +
                   "time and the input/output values — instead of a one-line summary. For anything " +
                   "that has to act on the answer rather than read it. Use with --against.")]
    public bool Trace { get; set; }

    [Option("keep", Required = false, MetaValue = "DIR",
        HelpText = "Keep the generated TLA+ here instead of discarding it: the module built from " +
                   "the policy text, the .cfg with the bounds, the raw TLC output, and a README " +
                   "saying how to re-run it. For checking the model rather than trusting the verdict.")]
    public string Keep { get; set; } = string.Empty;

    [Option("timeout", Required = false, HelpText = "Seconds before giving up (default 600).")]
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