namespace Anchor;

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

using static Result;

/// <summary>
/// Runs the Python half of Anchor — the translator and the checker — out of process.
/// </summary>
/// <remarks>
/// Out of process by measurement, not by default. In-process hosting via IronPython was tried and
/// rejected: the translator parses a policy in 0.10 ms while one checker run is ~5.6 s, because TLC
/// on a real JVM is the entire cost. Python is ~0.002% of the runtime, so embedding it saves
/// nothing and costs the language level — IronPython 3.4.2 is Python <em>3.4</em>, which rejects
/// <c>from __future__ import annotations</c> and therefore cannot import a single module in
/// <c>src/</c>.
/// <para>
/// This is the same shape as <c>TLCProcess</c>, deliberately: a subprocess, argv passed one element
/// per entry, output captured off the event handlers. A third runner would have been a third set of
/// quoting bugs.
/// </para>
/// </remarks>
public class PythonProcess : Runtime
{
    #region Methods

    /// <summary>
    /// Run a script from the Anchor tree. Failure means Python could not be run; a script that ran
    /// and disagreed reports itself in the run's exit code.
    /// </summary>
    /// <param name="script">Path to the script, relative to the Anchor root.</param>
    /// <param name="args">Arguments, one per element so that none of them is re-parsed.</param>
    /// <param name="timeout">Ten minutes by default: a checker run is many TLC invocations.</param>
    /// <param name="onOutput">Each stdout line as it arrives, as well as in the result.</param>
    /// <param name="onError">Each stderr line as it arrives, as well as in the result.</param>
    /// <param name="environment">Variables added to the child's environment.</param>
    public static async Task<Result<PythonRun>> RunAsync(string script, string[]? args = null,
        string? python = null, string? root = null, TimeSpan? timeout = null, CancellationToken ct = default,
        Action<string>? onOutput = null, Action<string>? onError = null,
        IReadOnlyDictionary<string, string>? environment = null)
    {
        if (!FindRoot(root).Succeeded(out var tree))
        {
            return Failure<PythonRun>(tree.Message);
        }
        if (!FindPython(python).Succeeded(out var exe))
        {
            return Failure<PythonRun>(exe.Message);
        }

        var full = Path.Combine(tree.Value, script);
        if (!File.Exists(full))
        {
            return Failure<PythonRun>($"The script {script} could not be found under {tree.Value}.");
        }

        var info = new ProcessStartInfo(exe.Value)
        {
            WorkingDirectory = tree.Value,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,

            // Redirected so the child gets its OWN stdin, empty, rather than inheriting ours.
            // Under the MCP stdio transport ours IS the protocol pipe, and handing a duplicate of
            // it to python -- and then to the java TLC spawns -- made CheckPolicy hang: it answered
            // in 5 seconds over HTTP and never at all over stdio. Nothing here reads stdin, which
            // is exactly why this was invisible until an agent drove the server the way a host
            // does.
            RedirectStandardInput = true,

            // UTF-8 both ways, with PYTHONUTF8 below: that makes the child WRITE UTF-8, and these
            // make us READ it. Left to defaults, Windows has the child write cp1252 and us read the
            // console's code page, so a checker relaying dogwood's box-drawn diagnostic crashed
            // writing it or arrived as mojibake.
            StandardOutputEncoding = utf8,
            StandardErrorEncoding = utf8
        };
        // ArgumentList quotes each element, which a joined string would not. These arguments are
        // policy paths that reach us from an agent, so a space in one is ordinary rather than
        // exotic.
        info.ArgumentList.Add(script);
        foreach (var arg in args ?? [])
        {
            info.ArgumentList.Add(arg);
        }

        // Unbuffered, so a caller watching a long run sees it progress instead of nothing followed
        // by everything.
        info.Environment["PYTHONUNBUFFERED"] = "1";
        info.Environment["PYTHONUTF8"] = "1";
        foreach (var (name, value) in environment ?? new Dictionary<string, string>())
        {
            info.Environment[name] = value;
        }

        // Collected either way; passed on as well when a caller wants to show a long run as it
        // happens rather than all at once at the end.
        var output = new StringBuilder();
        var errors = new StringBuilder();
        using var process = new Process { StartInfo = info };
        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            output.AppendLine(e.Data);
            onOutput?.Invoke(e.Data);
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            errors.AppendLine(e.Data);
            onError?.Invoke(e.Data);
        };

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout ?? TimeSpan.FromMinutes(10));

        try
        {
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            await process.WaitForExitAsync(cts.Token);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            // The tree, not just the interpreter: the checker spawns java, and an orphaned TLC
            // holds a core and its scratch directory for as long as it pleases.
            Kill(process);
            return Failure<PythonRun>(
                $"{script} did not finish within {(timeout ?? TimeSpan.FromMinutes(10)).TotalMinutes:0.#} minutes. " +
                $"A checker run is one TLC invocation per rule, so a large policy set or a high " +
                $"--attempts bound legitimately takes longer. Raise the timeout (--timeout SECONDS), or " +
                $"add --smoke N to search N random sessions instead of all of them.");
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            throw;
        }
        catch (Exception e)
        {
            return FailureWithError<PythonRun>($"Python could not be run: {e.Message}", e);
        }

        return Success(new PythonRun(process.ExitCode, output.ToString(), errors.ToString()));
    }

    /// <summary>
    /// The Anchor tree scripts are run from. <c>ANCHOR_ROOT</c> when set — which is how a container
    /// says so, having no <c>Anchor.sln</c> to find — otherwise the enclosing checkout.
    /// </summary>
    public static Result<string> FindRoot(string? root = null)
    {
        if (root is not null)
        {
            return Directory.Exists(root)
                ? Success(Path.GetFullPath(root))
                : Failure<string>($"No Anchor tree at {root}.");
        }

        // Checked before the solution walk, so the answer in a deployed image is never "it worked
        // on the dev box".
        var configured = Environment.GetEnvironmentVariable("ANCHOR_ROOT");
        if (!string.IsNullOrEmpty(configured) && Directory.Exists(configured))
        {
            return Success(Path.GetFullPath(configured));
        }

        var dir = new DirectoryInfo(string.IsNullOrEmpty(AssemblyLocation)
            ? Directory.GetCurrentDirectory() : AssemblyLocation);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "Anchor.sln")))
        {
            dir = dir.Parent;
        }

        return dir is not null
            ? Success(dir.FullName)
            : Failure<string>("No Anchor tree found. Set ANCHOR_ROOT to the repo or image root, " +
                              "or pass one explicitly.");
    }

    /// <summary>
    /// An interpreter that runs. The repo venv first when there is one, then PATH: the translator
    /// and the checker import nothing outside the standard library, so any working Python does.
    /// </summary>
    public static Result<string> FindPython(string? python = null)
    {
        if (python is not null)
        {
            return Runs(python) ? Success(python) : Failure<string>($"No usable Python at {python}.");
        }

        var names = OperatingSystem.IsWindows() ? ["python.exe"] : new[] { "python3", "python" };
        var candidates = new List<string>();

        if (FindRoot().Succeeded(out var tree))
        {
            var bin = Path.Combine(tree.Value, "python", OperatingSystem.IsWindows() ? "Scripts" : "bin");
            candidates.AddRange(names.Select(n => Path.Combine(bin, n)));
        }

        candidates.AddRange((Environment.GetEnvironmentVariable("PATH") ?? "")
            .Split(Path.PathSeparator)
            .Where(d => !string.IsNullOrWhiteSpace(d))
            .SelectMany(d => names.Select(n => Path.Combine(d, n))));

        var found = candidates.FirstOrDefault(Runs);
        return found is not null
            ? Success(found)
            : Failure<string>("No usable Python found. Put python on PATH, create the repo venv " +
                              "(requirements/strands/install.cmd), or pass one explicitly.");
    }

    /// <summary>Importable, not merely installed — a broken install is not a usable one.</summary>
    public static bool CanImport(string module, string? python = null) =>
        imports.GetOrAdd($"{python}\0{module}", _ =>
            FindPython(python).Succeeded(out var exe) && Execute(exe.Value, $"import {module}") is not null);

    static void Kill(Process process)
    {
        try { process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { /* raced us to exit */ }
    }

    /// <summary>
    /// Existing on disk proves nothing, and neither does answering <c>--version</c>. Windows ships
    /// an App Execution Alias at <c>WindowsApps\python.exe</c> that <c>File.Exists</c> reports
    /// happily and which only prints "Python was not found"; MSYS2's python answers
    /// <c>--version</c> and then cannot find its own stdlib when launched from a Windows process.
    /// Require it to execute something and say the answer back.
    /// </summary>
    static bool Runs(string exe) =>
        runnable.GetOrAdd(exe, e => File.Exists(e) && Execute(e, "print('anchor')") is string s && s.Contains("anchor"));

    /// <summary>Run one line of Python, or null if it did not exit cleanly.</summary>
    static string? Execute(string exe, string code)
    {
        try
        {
            var info = new ProcessStartInfo(exe)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            info.ArgumentList.Add("-c");
            info.ArgumentList.Add(code);

            using var probe = Process.Start(info);
            if (probe is null)
            {
                return null;
            }

            var stdout = probe.StandardOutput.ReadToEnd();
            if (!probe.WaitForExit(milliseconds: 60_000))
            {
                Kill(probe);
                return null;
            }
            return probe.ExitCode == 0 ? stdout : null;
        }
        catch (Exception)
        {
            // A candidate that throws is simply not the interpreter. The next one gets a turn.
            return null;
        }
    }

    #endregion

    #region Fields

    /// <summary>UTF-8 without a byte-order mark, which is what Python writes under PYTHONUTF8.</summary>
    static readonly Encoding utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    static readonly ConcurrentDictionary<string, bool> runnable = new();

    static readonly ConcurrentDictionary<string, bool> imports = new();

    #endregion
}

/// <summary>What a script did. <see cref="Succeeded"/> is the script's own verdict, not ours.</summary>
public record PythonRun(int ExitCode, string Output, string ErrorOutput)
{
    public bool Succeeded => ExitCode == 0;

    /// <summary>Everything the script said. On failure that is mostly the stderr half.</summary>
    public string All => string.IsNullOrEmpty(ErrorOutput) ? Output : Output + ErrorOutput;

    public override string ToString() => Succeeded ? Output : All;
}
