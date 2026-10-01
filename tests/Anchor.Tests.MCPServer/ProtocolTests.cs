namespace Anchor.Tests.MCPServer;

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;

using Anchor.MCPServer;

/// <summary>
/// The server driven by a real MCP client over HTTP, on an ephemeral port.
/// </summary>
/// <remarks>
/// <para>
/// <see cref="PolicyToolTests"/> calls the tool methods directly, which proves the checker is
/// wrapped correctly but says nothing about whether an agent can reach them: the schema the server
/// advertises, the serialisation of the result, and whether a refusal arrives as an answer or as a
/// transport error are all outside that. This suite is the part an agent host actually exercises.
/// </para>
/// <para>
/// HTTP rather than stdio because it is the transport a container exposes, and because the two
/// share one registration — see <c>AnchorMCPServer.Register</c>. A stdio-only defect would have to
/// live in the transport wiring itself, which is the SDK's code rather than ours.
/// </para>
/// </remarks>
public class ProtocolTests : TestsRuntime, IAsyncLifetime
{
    #region Methods

    public async Task InitializeAsync()
    {
        app = AnchorMCPServer.BuildHttpApp(projectDir: Repo);
        app.Urls.Clear();
        app.Urls.Add("http://127.0.0.1:0");
        await app.StartAsync();

        baseUrl = app.Services.GetRequiredService<IServer>()
            .Features.Get<IServerAddressesFeature>()!.Addresses.First();
    }

    public async Task DisposeAsync()
    {
        await app.StopAsync();
        await app.DisposeAsync();
    }

    /// <summary>
    /// The tool is advertised, and advertised with the guidance that makes it usable. The
    /// description is not decoration: an agent that cannot see that VACUOUS is bounded, or that the
    /// default reading is right only for a deployment that keeps Dogwood's default, will report a
    /// verdict more confidently than the verdict deserves.
    /// </summary>
    [PolicyCheck]
    public async Task TheCheckerIsAdvertisedWithItsCaveats()
    {
        await using var client = await NewClientAsync();

        var tools = await client.ListToolsAsync();
        var check = Assert.Single(tools, t => t.Name == "CheckPolicy");

        var description = check.Description ?? "";
        Assert.Contains("VACUOUS", description);
        Assert.Contains("THE BOUND IS REAL", description);
        Assert.Contains("PASS `eventSchema` WHENEVER ONE EXISTS", description);
        Assert.Contains("Dogwood's own default", description);

        // The one required argument, and the optional ones an agent needs to know exist.
        var schema = check.JsonSchema.ToString();
        Assert.Contains("policy", schema);
        Assert.Contains("eventSchema", schema);
        Assert.Contains("attempts", schema);
    }


    /// <summary>
    /// The two TLA+ tools an agent needs while WRITING a property module, rather than after.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Writing one is a three-step loop and each step had a tool except the middle two:
    /// <c>DescribePolicyModule</c> says what may be named, <c>CheckPolicy</c> says whether the
    /// claims hold — and between them sat "does this even compile" and "does it say what I meant",
    /// both of which an agent could previously only answer by paying for a full model-checking run
    /// and reading the reason out of TLC's preamble.
    /// </para>
    /// <para>
    /// Both are advertised with the guidance that makes them usable, which is asserted here because
    /// a description is not decoration: an agent that cannot see that a <c>vacuous</c> claim is a
    /// FINDING will report a green run as assurance.
    /// </para>
    /// </remarks>
    [PolicyCheck]
    public async Task TheSpecToolsAreReachableAndAdvertised()
    {
        await using var client = await NewClientAsync();

        var tools = await client.ListToolsAsync();

        var compile = Assert.Single(tools, t => t.Name == "CheckPropertyModule");
        Assert.Contains("SANY", compile.Description ?? "");
        // It needs the POLICY too, and an agent that does not know why will call it with the
        // module alone and read the failure as the module's fault.
        Assert.Contains("EXTENDS `PolicyUnderTest`", compile.Description ?? "");

        var explain = Assert.Single(tools, t => t.Name == "ExplainPropertyModule");
        Assert.Contains("forbids", explain.Description ?? "");
        Assert.Contains("vacuous", explain.Description ?? "");

        // --- a module that compiles -------------------------------------------------------------
        var ok = await client.CallToolAsync("CheckPropertyModule", new Dictionary<string, object?>
        {
            ["policy"] = "tests/policies/firewall.dw",
            ["property"] = "tests/policies/firewall.tla",
        });

        Assert.True(ok.IsError != true, Text(ok));
        Assert.Contains("compiles", Text(ok));

        // --- and what it forbids, in English ----------------------------------------------------
        var said = await client.CallToolAsync("ExplainPropertyModule", new Dictionary<string, object?>
        {
            ["property"] = "tests/policies/firewall.tla",
        });

        Assert.True(said.IsError != true, Text(said));

        var text = Text(said);
        Assert.Contains("LocalSshIsAllowed", text);
        Assert.Contains("OutsideIsRefused", text);
        // The sense of it, not merely its presence: a claim the policy must REFUSE forbids a GRANT.
        Assert.Contains("forbids", text);
        Assert.Contains("GRANTS", text);
    }


    /// <summary>
    /// The REPL: a TLA+ expression evaluated in a policy's own semantics, returning the value.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The tool for a QUESTION rather than a claim. <c>CheckPolicy</c> answers "does this hold in
    /// every state"; this answers "what IS this" — and most of what goes wrong while writing a
    /// property module is a value being something other than the author assumed: the units of a
    /// window, what a session actually contains, whether a set has the member they think.
    /// </para>
    /// <para>
    /// <b>It evaluates a policy DECISION</b>, which is what makes it more than a calculator:
    /// <c>TradeAllowed(960)</c> comes back TRUE or FALSE with no invariant written anywhere. A
    /// tuple asks two questions in one call, so the boundary of a temporal window is one command
    /// rather than a bisection — and the pair below is the 15-minute boundary of the article's
    /// trust-decay policy, which the Dogwood engine independently puts in the same place.
    /// </para>
    /// <para>
    /// Implemented out-of-process against TLC, and it has to be: in-process TLC is not viable under
    /// IKVM (see <c>TLCProcess</c>), and SANY — which IS in-process — only parses and resolves. It
    /// never evaluates.
    /// </para>
    /// </remarks>
    [PolicyCheck]
    public async Task AnExpressionCanBeEvaluatedInThePolicysSemantics()
    {
        await using var client = await NewClientAsync();

        var tools = await client.ListToolsAsync();
        var repl = Assert.Single(tools, t => t.Name == "EvaluateExpression");
        // An agent that reads this as a verdict will over-claim from one session.
        Assert.Contains("A VALUE IS NOT A VERDICT", repl.Description ?? "");

        var r = await client.CallToolAsync("EvaluateExpression", new Dictionary<string, object?>
        {
            ["policy"] = "examples/aws1/07-trust-decay.dw",
            ["property"] = "examples/aws1/TrustDecay10.tla",
            ["expression"] = "<<TradeAllowed(900), TradeAllowed(901)>>",
        });

        Assert.True(r.IsError != true, Text(r));

        // The reply is JSON, and the serializer escapes `<` and `>` as < / > — so a TLA+
        // tuple never appears literally in it. Decoded here rather than asserted in escaped form,
        // which would pin the serializer's encoding choice instead of the answer.
        var text = Text(r).Replace("\\u003C", "<").Replace("\\u003E", ">");

        // 900s: the advisor interacted within 15 minutes, so `unless` BLOCKS the permit and the
        // trade is denied. 901s: the window has passed, the block lifts, and the trade is allowed —
        // which is the inversion the article's own sentence forbids. One call, both sides.
        Assert.Contains("<<FALSE, TRUE>>", text);
    }

    /// <summary>A verdict, end to end, through the pipeline an agent host uses.</summary>
    [PolicyCheck]
    public async Task CheckPolicyReturnsAVerdictOverTheProtocol()
    {
        await using var client = await NewClientAsync();

        var r = await client.CallToolAsync("CheckPolicy", new Dictionary<string, object?>
        {
            ["policy"] = "tests/policies/dead_forbid.dw"
        });

        Assert.True(r.IsError != true, Text(r));

        var text = Text(r);
        Assert.Contains("DEAD", text);
        Assert.Contains("forbid", text);

        // The caveat has to survive serialisation too, not merely exist on the record. Matched on
        // words with no apostrophe: the JSON encoder writes one as '.
        Assert.Contains("callerPrincipal pinned", text, StringComparison.Ordinal);
    }

    /// <summary>
    /// A refused policy comes back as an ANSWER saying it was refused, not as a protocol error and
    /// not as an empty pass. An agent distinguishes the three differently, and only one of them is
    /// true here.
    /// </summary>
    [PolicyCheck]
    public async Task ARefusalArrivesAsAnAnswer()
    {
        await using var client = await NewClientAsync();

        var r = await client.CallToolAsync("CheckPolicy", new Dictionary<string, object?>
        {
            ["policy"] = "tests/policies/like_impossible.dw"
        });

        var text = Text(r);
        Assert.Contains("REFUSED", text);
        Assert.Contains("glob intersection", text);

        // "answered: false", not "findings: []". The difference is the whole point.
        Assert.Contains("false", text, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Containment holds across the protocol boundary. Reached this way the refusal is an argument
    /// error rather than an exception, so it must still be visibly a refusal.
    /// </summary>
    [PolicyCheck]
    public async Task APathOutsideTheProjectIsRefusedOverTheProtocol()
    {
        await using var client = await NewClientAsync();

        var r = await client.CallToolAsync("CheckPolicy", new Dictionary<string, object?>
        {
            ["policy"] = "../../CLAUDE.md"
        });

        // BOTH, now: an error the caller can branch on, carrying the reason. The server's tool filter
        // answers the refusal itself, rather than the SDK logging it as an unhandled exception.
        var text = Text(r);
        Assert.True(r.IsError == true, $"a path escaping the project was not refused: {text}");
        Assert.Contains("outside this project's directory", text);
    }

    /// <summary>
    /// The describe tool is reachable and cheap. Its whole value is being called BEFORE a property
    /// module is written, so a tool an agent cannot find is a tool that does not exist.
    /// </summary>
    [PolicyCheck]
    public async Task DescribePolicyModuleIsReachableAndFast()
    {
        await using var client = await NewClientAsync();

        var tools = await client.ListToolsAsync();
        var describe = Assert.Single(tools, t => t.Name == "DescribePolicyModule");
        Assert.Contains("Num(22)", describe.Description ?? "");

        var r = await client.CallToolAsync("DescribePolicyModule", new Dictionary<string, object?>
        {
            ["policy"] = "tests/policies/firewall.dw"
        });

        Assert.True(r.IsError != true, Text(r));

        var text = Text(r);
        Assert.Contains("Connect", text);
        Assert.Contains("skeleton", text);
        Assert.Contains("PolicyUnderTest", text);

        // NO WALL-CLOCK ASSERTION HERE, deliberately. There was one — "under ten seconds, so it
        // cannot be running TLC" — and it failed once inside the full parallel suite while passing
        // in 615 ms alone. Raising the bound would not have fixed it: an exhaustive check of this
        // same policy takes about five seconds, so any bound loose enough to survive a loaded
        // machine is also loose enough to let a model-checking regression through. The assertion
        // could not distinguish what it claimed to even when it passed.
        //
        // That this tool parses only is documented, not asserted. A flaky test costs more than a
        // guard that never worked.
    }

    /// <summary>
    /// The knowledge base over the wire, both ways it is offered. Needs no Python and no JVM, so it
    /// is a plain Fact: a host with neither should still be able to read the reference.
    /// </summary>
    [Fact]
    public async Task TheKnowledgeBaseIsReachableAsToolsAndAsResources()
    {
        await using var client = await NewClientAsync();

        var tools = await client.ListToolsAsync();
        Assert.Single(tools, t => t.Name == "ListKnowledge");
        Assert.Single(tools, t => t.Name == "ReadKnowledge");

        var listed = await client.CallToolAsync("ListKnowledge", new Dictionary<string, object?>());
        Assert.True(listed.IsError != true, Text(listed));
        Assert.Contains("reading-verdicts", Text(listed));

        var read = await client.CallToolAsync("ReadKnowledge", new Dictionary<string, object?>
        {
            ["names"] = new[] { "reading-verdicts" }
        });
        Assert.True(read.IsError != true, Text(read));
        Assert.Contains("VACUOUS", Text(read));

        // And as resources, for a host that reads those instead.
        var resources = await client.ListResourcesAsync();
        var article = Assert.Single(resources, r => r.Uri == "anchor://knowledge/reading-verdicts");

        var contents = await client.ReadResourceAsync(article.Uri);
        Assert.Contains("VACUOUS", string.Concat(contents.Contents.OfType<TextResourceContents>().Select(c => c.Text)));
    }

    async Task<McpClient> NewClientAsync()
    {
        var transport = new HttpClientTransport(
            new HttpClientTransportOptions { Endpoint = new Uri(baseUrl) },
            NullLoggerFactory.Instance);
        return await McpClient.CreateAsync(transport);
    }

    static string Text(CallToolResult r) =>
        string.Concat(r.Content.OfType<TextContentBlock>().Select(c => c.Text));

    #endregion

    #region Fields

    static readonly string Repo = PythonProcess.FindRoot().IsSuccess
        ? PythonProcess.FindRoot().Value : Directory.GetCurrentDirectory();

    WebApplication app = null!;

    string baseUrl = "";

    #endregion
}
