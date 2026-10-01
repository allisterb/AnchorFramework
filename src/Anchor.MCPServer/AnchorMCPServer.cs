namespace Anchor.MCPServer;

using System;
using System.IO;
using System.Threading.Tasks;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

/// <summary>
/// The Anchor MCP server, over stdio or HTTP.
/// </summary>
/// <remarks>
/// One tool registration, two transports. Stdio is how an MCP host on a developer's machine speaks
/// to it; HTTP is what a container exposes. They are the same server with the same tools, which is
/// the point — a deployment that only ever ran over HTTP would be a second configuration nobody
/// exercises locally.
/// </remarks>
public class AnchorMCPServer : Runtime
{
    #region Methods

    /// <summary>Serve over stdio, for an MCP host that launches us as a child process.</summary>
    /// <remarks>
    /// <b>Runtime logging must be file-only before this is called</b> — <c>Runtime.WithFileLogging</c>,
    /// never <c>WithFileAndConsoleLogging</c> — because the host's logging is sent to that provider,
    /// and one log line on stdout corrupts the JSON-RPC stream. The CLI guarantees it for a stdio
    /// launch, redirects <c>Console.Out</c> to stderr as a second guard, and
    /// <c>StdioTransportTests</c> parses every line the process writes to hold it to that.
    /// </remarks>
    public static async Task RunStdioAsync(string? projectDir = null, string? anchorRoot = null)
    {
        var builder = Host.CreateEmptyApplicationBuilder(null);

        // Nothing may be written to stdout but MCP frames — a stray log line corrupts the protocol.
        // Anchor's provider is safe here because the CLI configures it file-only for a stdio launch;
        // before, the SDK's own logging was cleared and went nowhere, a failed tool call included.
        UseAnchorLogging(builder.Logging);

        Register(builder.Services.AddMcpServer(), projectDir, anchorRoot).WithStdioServerTransport();

        await builder.Build().RunAsync();
    }

    /// <summary>Serve over HTTP. This is the shape a container exposes.</summary>
    public static async Task RunHttpAsync(int? port = null, string? projectDir = null, string? anchorRoot = null)
        => await BuildHttpApp(port, projectDir, anchorRoot).RunAsync();

    public static WebApplication BuildHttpApp(int? port = null, string? projectDir = null, string? anchorRoot = null)
    {
        var builder = WebApplication.CreateBuilder();

        // 0.0.0.0, not localhost: a container binding the loopback accepts nothing from outside
        // itself, which presents as a health check that never passes and a server that looks fine
        // from inside a shell on the same container.
        builder.WebHost.UseUrls($"http://0.0.0.0:{port ?? DefaultPort}");

        // The host's defaults include the Windows Event Log, which is where a refused tool call
        // used to end up -- and not in Anchor's own log, which never saw it.
        UseAnchorLogging(builder.Logging);

        Register(builder.Services.AddMcpServer(), projectDir, anchorRoot).WithHttpTransport();

        var app = builder.Build();
        app.MapMcp();

        // A liveness probe that does not depend on the model, the toolchain, or a session.
        app.MapGet("/ping", () => Results.Ok(new { status = "ok" }));

        app.Lifetime.ApplicationStarted.Register(() =>
        {
            var addresses = app.Services.GetService<IServer>()?.Features.Get<IServerAddressesFeature>()?.Addresses;
            foreach (var address in addresses ?? [])
            {
                Info("Anchor MCP server listening on {0} (project directory: {1}).",
                    address, projectDir ?? Directory.GetCurrentDirectory());
            }
        });

        return app;
    }

    /// <summary>
    /// The one registration both transports share. Also the place the toolchain is checked: a
    /// server that starts happily and fails every call is worse than one that says why at boot.
    /// </summary>
    static IMcpServerBuilder Register(IMcpServerBuilder mcp, string? projectDir, string? anchorRoot)
    {
        var tools = new PolicyTools(projectDir, anchorRoot);

        var root = PythonProcess.FindRoot(anchorRoot);
        var python = PythonProcess.FindPython();
        if (!root.IsSuccess)
        {
            Warn("The Anchor tree was not found: {0} Policy tools will report this on every call.", root.Message ?? "");
        }
        else if (!python.IsSuccess)
        {
            Warn("No usable Python: {0} Policy tools will report this on every call.", python.Message ?? "");
        }
        else
        {
            Info("Anchor tree at {0}, Python at {1}.", root.Value, python.Value);
        }

        mcp.WithTools(tools);
        mcp.WithTools<KnowledgeTools>();

        // A PATH OUTSIDE THE PROJECT IS A REFUSAL, NOT A FAULT. Thrown out of a tool it reached the
        // SDK as an unhandled exception, logged with a stack trace as a failure. Answered here as a
        // tool error instead -- the caller is told exactly why -- with one warning line in the log,
        // because an agent reaching outside its directory is worth a record.
        mcp.WithRequestFilters(filters => filters.AddCallToolFilter(next => async (request, ct) =>
        {
            try
            {
                return await next(request, ct);
            }
            catch (OutsideProjectException e)
            {
                Warn("Refused a call to {0}: {1}", request.Params?.Name ?? "a tool", e.Message);
                return new CallToolResult { IsError = true, Content = [new TextContentBlock { Text = e.Message }] };
            }
        }));

        // The same articles twice, by design. Resources are the natural fit; some hosts never
        // surface them, and a reference an agent cannot reach is one that does not exist.
        mcp.WithResources(KnowledgeBase.Resources());

        Info("{0} knowledge-base article(s) registered.", KnowledgeBase.Articles.Count);

        return mcp;
    }

    /// <summary>
    /// The host's logging, sent to the provider the CLI configured -- Anchor's own log file -- and
    /// nowhere else. As Polson.MCPServer does. ASP.NET Core's per-request lines are held to
    /// warnings, so the file records tool calls and failures rather than every HTTP request.
    /// </summary>
    static void UseAnchorLogging(ILoggingBuilder logging) =>
        logging.ClearProviders()
            .AddProvider(loggerProvider)
            .SetMinimumLevel(LogLevel.Information)
            .AddFilter("Microsoft.AspNetCore", LogLevel.Warning);

    #endregion

    #region Fields

    /// <summary>8080, which is what a container is conventionally expected to listen on.</summary>
    public const int DefaultPort = 8080;

    #endregion
}
