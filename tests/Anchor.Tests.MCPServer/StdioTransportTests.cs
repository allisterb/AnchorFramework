namespace Anchor.Tests.MCPServer;

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

using Microsoft.Extensions.Logging.Abstractions;

using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;

/// <summary>
/// The shipped <c>anchor</c> binary, launched as a child process and driven down one pipe — which
/// is exactly what an MCP host's stdio wiring does.
/// </summary>
/// <remarks>
/// <para>
/// THE THING THIS PROVES THAT NOTHING ELSE CAN. Under stdio, standard output carries MCP frames and
/// nothing else. A single log line written there corrupts the session, and the symptom is a host
/// reporting a malformed response — nothing that names logging. Every other test in this project
/// either calls the tools in-process or speaks HTTP, so none of them would notice.
/// </para>
/// <para>
/// It is also the only test that exercises the CLI at all: the verb dispatch, the default verb, and
/// the choice of a file-only log sink for this transport.
/// </para>
/// <para>
/// Skipped when the CLI has not been built, rather than failing — the same rule the Dogwood harness
/// follows. A skip is visible in the run summary; a silent pass would be worse than no test.
/// </para>
/// </remarks>
public class StdioTransportTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// A full session over stdio: initialize, list, and call. If anything but protocol reaches
    /// stdout, the client fails to parse and this test is how we find out.
    /// </summary>
    [CliFact]
    public async Task TheCliServesMcpOverStdioWithACleanStdout()
    {
        await using var client = await NewClientAsync();

        var tools = await client.ListToolsAsync();
        Assert.Contains(tools, t => t.Name == "CheckPolicy");
        Assert.Contains(tools, t => t.Name == "DescribePolicyModule");
        Assert.Contains(tools, t => t.Name == "ListKnowledge");

        // A real call, so the pipe carries a response as well as a handshake. Knowledge needs
        // neither Python nor a JVM, which keeps this test about the transport.
        var read = await client.CallToolAsync("ReadKnowledge", new Dictionary<string, object?>
        {
            ["names"] = new[] { "reading-verdicts" }
        });

        Assert.True(read.IsError != true, Text(read));
        Assert.Contains("VACUOUS", Text(read));
    }

    /// <summary>
    /// Resources too, since a host may read those instead of calling tools, and they travel the
    /// same pipe.
    /// </summary>
    [CliFact]
    public async Task KnowledgeResourcesSurviveTheStdioTransport()
    {
        await using var client = await NewClientAsync();

        var resources = await client.ListResourcesAsync();
        var article = Assert.Single(resources, r => r.Uri == "anchor://knowledge/smoke-vs-exhaustive");

        var contents = await client.ReadResourceAsync(article.Uri);
        Assert.Contains("never report VACUOUS",
            string.Concat(contents.Contents.OfType<TextResourceContents>().Select(c => c.Text)));
    }

    /// <summary>
    /// A tool that SPAWNS A CHILD PROCESS, over stdio. This is the gap that let a real bug ship.
    /// </summary>
    /// <remarks>
    /// The stdio tests above call knowledge tools, which run in-process; the one test that called
    /// <c>CheckPolicy</c> spoke HTTP to an in-process server. So no test ever ran the tool that
    /// starts python — and then java — while the server's own stdin was an MCP pipe.
    /// <para>
    /// It hung, forever, and only over stdio: <c>PythonProcess</c> did not redirect the child's
    /// stdin, so python inherited the protocol pipe. Five seconds over HTTP, never over stdio,
    /// which is the transport every MCP host actually uses. Found by pointing an agent at the
    /// server, not by any test we had.
    /// </para>
    /// </remarks>
    [CliPolicyFact]
    public async Task AToolThatSpawnsAChildProcessAnswersOverStdio()
    {
        await using var client = await NewClientAsync();

        var r = await client.CallToolAsync("CheckPolicy", new Dictionary<string, object?>
        {
            ["policy"] = "tests/policies/dead_forbid.dw"
        });

        Assert.True(r.IsError != true, Text(r));

        var text = Text(r);
        Assert.Contains("DEAD", text);
        // No apostrophe in what is matched: the JSON encoder writes one as '.
        Assert.Contains("callerPrincipal pinned", text, StringComparison.Ordinal);
    }

    /// <summary>
    /// EVERY line on stdout is a JSON-RPC message. Asserted directly, against the raw pipe.
    /// </summary>
    /// <remarks>
    /// The two tests above do NOT establish this, which was worth finding out: a stray
    /// <c>Console.WriteLine</c> was added to the stdio path deliberately and both still passed. The
    /// client skips lines it cannot parse, so a working session proves the frames arrived, not that
    /// they arrived alone. A host that is stricter — or one that logs the noise — is the one that
    /// suffers, and by then the cause is far away.
    /// <para>
    /// So this one reads the child's stdout itself and parses every line.
    /// </para>
    /// </remarks>
    [CliFact]
    public async Task NothingButProtocolReachesStdout()
    {
        var info = new System.Diagnostics.ProcessStartInfo("dotnet")
        {
            WorkingDirectory = Repo,
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        foreach (var arg in new[] { CliDll, "server", "--project-dir", Repo })
        {
            info.ArgumentList.Add(arg);
        }

        var lines = new System.Collections.Concurrent.ConcurrentQueue<string>();
        using var process = System.Diagnostics.Process.Start(info)!;
        var pump = Task.Run(async () =>
        {
            string? line;
            while ((line = await process.StandardOutput.ReadLineAsync()) is not null)
            {
                lines.Enqueue(line);
            }
        });

        await process.StandardInput.WriteLineAsync(
            """{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}""");
        await process.StandardInput.WriteLineAsync("""{"jsonrpc":"2.0","method":"notifications/initialized"}""");
        await process.StandardInput.WriteLineAsync("""{"jsonrpc":"2.0","id":2,"method":"tools/list"}""");
        await process.StandardInput.FlushAsync();

        // Wait for the reply to id 2, so the pipe has carried a real exchange before we judge it.
        // Generous on purpose: the loop exits the moment the reply lands, so a long bound costs
        // nothing when the machine is idle and stops the test starving when the rest of the suite
        // is running in parallel. A shorter one here would be the same mistake a wall-clock
        // assertion in ProtocolTests already made once.
        var deadline = DateTime.UtcNow.AddMinutes(2);
        while (DateTime.UtcNow < deadline && !lines.Any(l => l.Contains("\"id\":2")))
        {
            await Task.Delay(200);
        }

        process.StandardInput.Close();
        try { await process.WaitForExitAsync(new System.Threading.CancellationTokenSource(15_000).Token); }
        catch (OperationCanceledException) { process.Kill(entireProcessTree: true); }
        await pump;

        var captured = lines.ToArray();
        Assert.NotEmpty(captured);
        Assert.Contains(captured, l => l.Contains("CheckPolicy"));

        foreach (var line in captured.Where(l => !string.IsNullOrWhiteSpace(l)))
        {
            // The assertion the mutation exposed: not "the session worked", but "this line is a
            // protocol message". A log line fails here and names itself.
            var parsed = Record.Exception(() =>
            {
                using var doc = System.Text.Json.JsonDocument.Parse(line);
                Assert.True(doc.RootElement.TryGetProperty("jsonrpc", out _),
                    $"a line on stdout is JSON but not a JSON-RPC message: {line}");
            });
            Assert.True(parsed is null, $"a non-protocol line reached stdout: {line}");
        }
    }

    /// <summary>Starts one server process. Disposing the client stops it.</summary>
    static async Task<McpClient> NewClientAsync()
    {
        var transport = new StdioClientTransport(new StdioClientTransportOptions
        {
            Name = "anchor",
            Command = "dotnet",
            Arguments = [CliDll, "server", "--project-dir", Repo],
            WorkingDirectory = Repo,
        }, NullLoggerFactory.Instance);

        return await McpClient.CreateAsync(transport);
    }

    static string Text(CallToolResult r) =>
        string.Concat(r.Content.OfType<TextContentBlock>().Select(c => c.Text));

    #endregion

    #region Fields

    internal static readonly string Repo = PythonProcess.FindRoot().IsSuccess
        ? PythonProcess.FindRoot().Value : Directory.GetCurrentDirectory();

    /// <summary>
    /// The CLI built in the SAME configuration as this test, taken from this assembly's own path
    /// rather than assumed to be Debug — a Release test run must exercise the Release binary.
    /// </summary>
    internal static readonly string CliDll = Path.Combine(
        Repo, "src", "Anchor.CLI", "bin",
        new DirectoryInfo(AppContext.BaseDirectory).Parent?.Name ?? "Debug",
        new DirectoryInfo(AppContext.BaseDirectory).Name,
        "Anchor.CLI.dll");

    #endregion
}

/// <summary>A fact needing the built <c>anchor</c> CLI, which a test-only build will not have.</summary>
[AttributeUsage(AttributeTargets.Method)]
public sealed class CliFactAttribute : FactAttribute
{
    public CliFactAttribute()
    {
        if (!File.Exists(StdioTransportTests.CliDll))
        {
            Skip = $"the anchor CLI is not built at {StdioTransportTests.CliDll} — build the solution first";
        }
    }
}
