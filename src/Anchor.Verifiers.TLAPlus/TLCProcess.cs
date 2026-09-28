namespace Anchor.Verifiers.TLAPlus;

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

using tlc2.output;

using static Result;

/// <summary>
/// Runs TLC out-of-process against a real JVM and parses its machine-readable output.
///
/// In-process TLC is not viable under IKVM: every run constructs an FPSet, which derives from
/// java.rmi.server.UnicastRemoteObject, and IKVM's RMI export check rejects FPSetRMI.put because it
/// declares java.io.IOException rather than RemoteException — legal on a real JVM, where
/// RemoteException extends IOException. Argument parsing also reaches java.lang.String.strip, a
/// Java 11 method absent from IKVM's Java 8 class library.
///
/// The <c>-tool</c> flag frames every message as
/// <c>@!@!@STARTMSG code:severity @!@!@ ... @!@!@ENDMSG code @!@!@</c>. The delimiters, severities
/// and codes below are the constants out of the same jar being parsed, so they move with it on an
/// upgrade instead of drifting from hand-copied literals.
/// </summary>
public class TLCProcess : Runtime
{
    #region Methods

    /// <summary>Model-check a spec. Failure means TLC could not be run; inspect the run for what it found.</summary>
    public static async Task<Result<TLCRun>> CheckAsync(string spec, string? config = null, string? jar = null,
        string? java = null, string[]? args = null, CancellationToken ct = default)
    {
        if (!File.Exists(spec))
        {
            return Failure<TLCRun>($"The spec {spec} could not be found.");
        }
        if (config is not null && !File.Exists(config))
        {
            return Failure<TLCRun>($"The config {config} could not be found.");
        }
        if (!FindJava(java).Succeeded(out var jvm) || !FindJar(jar).Succeeded(out var tools))
        {
            return Failure<TLCRun>(jvm.IsSuccess ? FindJar(jar).Message : jvm.Message);
        }

        // TLC writes its state files to states/<timestamp>/ under the working directory, and -cleanup
        // does not remove them after a run that found a violation. Point -metadir at a scratch
        // directory instead, so a check never writes into the directory holding the spec.
        var metadir = Path.Combine(Path.GetTempPath(), "anchor-tlc", Path.GetRandomFileName());
        Directory.CreateDirectory(metadir);

        // -Djava.io.tmpdir must come BEFORE the class name, and it is not optional. TLC extracts
        // the TLA+ standard modules -- Naturals.tla and friends -- into the JVM temp directory, so
        // without this every concurrent TLC writes the same files into the one shared %TEMP%. Two
        // racing runs leave one of them reading a half-written Naturals.tla, and SANY reports it as
        // a NullPointerException followed by "Module-Table lookup failure" naming whichever spec
        // happened to lose: a failure that points at an unrelated, perfectly good file. It cost
        // about one run in four before this line.
        // Extra JVM flags, from ANCHOR_TLC_JAVA_OPTS. The same knob the Python runner reads, so
        // there is one of them rather than two, and it is empty unless something sets it — a run
        // started by a person gets whatever the JVM's own defaults are. The test suite sets
        // -XX:TieredStopAtLevel=1, which is a large win when six model checks compete for the
        // machine and a large LOSS on a search big enough to profit from the optimising compiler;
        // tests/*/anchor.runsettings carries the measurements.
        var argv = new List<string>(
            (Environment.GetEnvironmentVariable("ANCHOR_TLC_JAVA_OPTS") ?? "")
                .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            // UTF-8 in and out, as in src/translator/tlc.py: the JVM's default charset is the
            // platform's -- cp1252 on Windows -- for reading .tla files and for writing stdout.
            // file.encoding covers both on Java 11-17; stdout/stderr.encoding are Java 19+, and a
            // JVM ignores properties it does not know.
            "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
            $"-Djava.io.tmpdir={metadir}",
            "-cp", tools.Value, "tlc2.TLC", "-tool", "-metadir", metadir
        };
        if (config is not null)
        {
            argv.AddRange(["-config", Path.GetFullPath(config)]);
        }
        argv.AddRange(args ?? []);
        argv.Add(Path.GetFullPath(spec));

        var info = new ProcessStartInfo(jvm.Value)
        {
            WorkingDirectory = Path.GetDirectoryName(Path.GetFullPath(spec)),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // Stated, because the default for a redirected stream on Windows is the console's code
            // page -- whatever that happens to be -- not what the JVM was told to write.
            StandardOutputEncoding = utf8,
            StandardErrorEncoding = utf8
        };
        // ArgumentList quotes each element, which a joined string would not: both the JDK path and
        // the spec paths routinely contain spaces.
        argv.ForEach(info.ArgumentList.Add);

        var output = new StringBuilder();
        var errors = new StringBuilder();
        using var process = new Process { StartInfo = info };
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) output.AppendLine(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is not null) errors.AppendLine(e.Data); };

        try
        {
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            await process.WaitForExitAsync(ct);
        }
        catch (Exception e)
        {
            return FailureWithError<TLCRun>($"TLC could not be run: {e.Message}", e);
        }
        finally
        {
            try { Directory.Delete(metadir, true); } catch (IOException) { /* scratch; leave it */ }
        }

        var text = output.ToString();
        return Success(new TLCRun(process.ExitCode, Parse(text), text, errors.ToString()));
    }

    /// <summary>Split <c>-tool</c> output into its STARTMSG/ENDMSG blocks. Unframed lines are ignored.</summary>
    public static IReadOnlyList<TLCMessage> Parse(string output)
    {
        var messages = new List<TLCMessage>();
        var start = MP.DELIM + MP.STARTMSG;
        var end = MP.DELIM + MP.ENDMSG;
        var text = (List<string>?)null;
        var (code, severity) = (0, 0);

        foreach (var line in output.Split('\n').Select(l => l.TrimEnd('\r')))
        {
            if (text is null && line.StartsWith(start))
            {
                // "@!@!@STARTMSG 2110:1 @!@!@"
                var header = line[start.Length..].Replace(MP.DELIM, "").Trim().Split(MP.COLON);
                if (header.Length == 2 && int.TryParse(header[0], out code) && int.TryParse(header[1], out severity))
                {
                    text = [];
                }
            }
            else if (text is not null && line.StartsWith(end))
            {
                messages.Add(new TLCMessage(code, Name(code), severity, string.Join(Environment.NewLine, text).Trim()));
                text = null;
            }
            else
            {
                text?.Add(line);
            }
        }
        return messages;
    }

    /// <summary>The <c>tlc2.output.EC</c> constant name for a code, or the number if it has none.</summary>
    public static string Name(int code) => codeNames.Value.TryGetValue(code, out var name) ? name : code.ToString();

    /// <summary>The JVM to run TLC on: the argument, then JAVA_HOME, then java on PATH.</summary>
    public static Result<string> FindJava(string? java = null)
    {
        if (java is not null)
        {
            return File.Exists(java) ? Success(java) : Failure<string>($"No JVM at {java}.");
        }
        var exe = OperatingSystem.IsWindows() ? "java.exe" : "java";
        var home = Environment.GetEnvironmentVariable("JAVA_HOME");
        if (!string.IsNullOrEmpty(home) && File.Exists(Path.Combine(home, "bin", exe)))
        {
            return Success(Path.Combine(home, "bin", exe));
        }
        var path = Environment.GetEnvironmentVariable("PATH")?
            .Split(Path.PathSeparator)
            .Select(d => Path.Combine(d, exe))
            .FirstOrDefault(File.Exists);
        return path is not null
            ? Success(path)
            : Failure<string>("No JVM found. Set JAVA_HOME, or put java on PATH, or pass one explicitly. " +
                              "tla2tools 1.7.4 needs Java 11 or later.");
    }

    /// <summary>
    /// The tla2tools jar: the argument, then TLA2TOOLS_JAR, then beside this assembly. The build
    /// copies it under its versioned name, so match that first and fall back to the bare name.
    /// </summary>
    public static Result<string> FindJar(string? jar = null)
    {
        // Versioned name first: an unversioned tla2tools.jar sorts after "tla2tools-1.7.4.jar" on a
        // plain ordinal sort ('.' > '-'), which would silently prefer a stale drop-in.
        var beside = Directory.EnumerateFiles(AssemblyLocation, "tla2tools*.jar").ToList();
        var candidates = new[] { jar, Environment.GetEnvironmentVariable("TLA2TOOLS_JAR") }
            .Where(c => !string.IsNullOrEmpty(c))
            .Concat(beside.Where(f => Path.GetFileName(f).StartsWith("tla2tools-")).OrderDescending())
            .Concat(beside.Where(f => !Path.GetFileName(f).StartsWith("tla2tools-")));
        var found = candidates.FirstOrDefault(c => File.Exists(c));
        return found is not null
            ? Success(Path.GetFullPath(found))
            : Failure<string>("tla2tools.jar not found. Pass a path, set TLA2TOOLS_JAR, " +
                              $"or place it beside the assembly at {AssemblyLocation}.");
    }

    #endregion

    #region Fields

    /// <summary>UTF-8 without a byte-order mark, which is what the JVM writes when told UTF-8.</summary>
    private static readonly Encoding utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    private static readonly Lazy<Dictionary<int, string>> codeNames = new(() =>
        typeof(EC).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(f => f.IsLiteral && f.FieldType == typeof(int))
            .GroupBy(f => (int)f.GetValue(null)!)
            .ToDictionary(g => g.Key, g => g.First().Name));

    #endregion
}

/// <summary>
/// The TLC message codes worth naming, taken from <c>tlc2.output.EC</c> in the jar being parsed.
/// These are <c>const</c>, so they inline into callers and consumers need no reference to the
/// IKVM-generated assembly — which does not flow transitively anyway.
/// </summary>
public static class TLCCodes
{
    public const int Success = EC.TLC_SUCCESS;
    public const int Finished = EC.TLC_FINISHED;
    public const int InvariantViolated = EC.TLC_INVARIANT_VIOLATED_BEHAVIOR;
    public const int InvariantViolatedInitial = EC.TLC_INVARIANT_VIOLATED_INITIAL;
    public const int PropertyViolated = EC.TLC_PROPERTY_VIOLATED_INITIAL;
    public const int TemporalPropertyViolated = EC.TLC_TEMPORAL_PROPERTY_VIOLATED;
    public const int ActionPropertyViolated = EC.TLC_ACTION_PROPERTY_VIOLATED_BEHAVIOR;
    public const int DeadlockReached = EC.TLC_DEADLOCK_REACHED;
    public const int StatePrint = EC.TLC_STATE_PRINT2;
    public const int Statistics = EC.TLC_STATS;
    public const int Version = EC.TLC_VERSION;

    /// <summary>Closes a lasso: the trace returns here, so the cycle repeats forever.</summary>
    public const int BackToState = EC.TLC_BACK_TO_STATE;

    public const int CounterExample = EC.TLC_COUNTER_EXAMPLE;
}

/// <summary>One framed TLC message. <paramref name="Severity"/> is an <c>MP</c> level.</summary>
public record TLCMessage(int Code, string Name, int Severity, string Text)
{
    public bool IsError => Severity == MP.ERROR || Severity == MP.TLCBUG;

    public bool IsWarning => Severity == MP.WARNING;

    /// <summary>Part of a counterexample trace: one state TLC printed on the way to a violation.</summary>
    public bool IsState => Severity == MP.STATE;

    public override string ToString() => $"{Name}({Code}): {Text}";
}

/// <summary>A completed TLC run.</summary>
public record TLCRun(int ExitCode, IReadOnlyList<TLCMessage> Messages, string Output, string ErrorOutput)
{
    /// <summary>TLC explored the state space and found no violation.</summary>
    public bool Verified => ExitCode == 0 && Messages.Any(m => m.Code == EC.TLC_SUCCESS);

    public IEnumerable<TLCMessage> Errors => Messages.Where(m => m.IsError);

    public IEnumerable<TLCMessage> Warnings => Messages.Where(m => m.IsWarning);

    /// <summary>The counterexample, in the order TLC printed it. Empty when nothing was violated.</summary>
    public IEnumerable<TLCMessage> Trace => Messages.Where(m => m.IsState);

    public override string ToString() =>
        Verified ? "Verified." : string.Join(Environment.NewLine, Errors.Select(e => e.ToString()));
}
