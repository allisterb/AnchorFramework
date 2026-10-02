namespace Anchor.Tests.MCPServer;

using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;

using Anchor.MCPServer;

/// <summary>
/// <c>CheckDecisionTable</c> — a policy set against sessions and the decisions they should get.
/// </summary>
/// <remarks>
/// The tool's job is to make "does this policy do what was meant" mechanical, so the tests that
/// matter are the ones where it must NOT say yes: a wrong expectation comes back as a disagreement
/// with both verdicts, not as an error and not as a pass; and a table that could not have been
/// recorded comes back as malformed, not checked, because a wrong row is a wrong oracle.
/// </remarks>
public class DecisionTableTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// A table that matches the policy: every decision agrees, and where the engine ran, the model and
    /// the engine agree with each other too -- on the verdict and on which rules decided it.
    /// </summary>
    [PolicyCheck]
    public async Task ATableThePolicyMeetsAgreesEverywhere()
    {
        var tools = new PolicyTools(projectRoot: Repo);
        var r = await tools.CheckDecisionTableAsync(
            Path.Combine("examples", "aws1", "tables", "05-human-approval.dw"),
            table: Path.Combine("examples", "aws1", "tables", "05-human-approval.dw"),
            policySchema: Path.Combine("examples", "aws1", "tables", "blog.cedarschema"));

        Assert.True(r.Answered, r.Error);
        var doc = r.Result!.Value;
        Assert.Contains("AgentCore", doc.GetProperty("reading").GetString());

        var totals = doc.GetProperty("totals");
        Assert.True(totals.GetProperty("decisions").GetInt32() > 0);
        Assert.Equal(0, totals.GetProperty("disagree").GetInt32());
        Assert.Equal(0, totals.GetProperty("modelVersusEngine").GetInt32());

        // Every decision says which rules decided it, so a reader can tell the right verdict reached
        // through the wrong rule from the right one.
        var decisions = doc.GetProperty("rows").EnumerateArray()
            .SelectMany(row => row.GetProperty("decisions").EnumerateArray()).ToList();
        Assert.All(decisions, d => Assert.True(d.TryGetProperty("modelRules", out _)));
    }

    /// <summary>
    /// A wrong expectation is the answer most worth having, so it must come back AS an answer: the
    /// decision, what the table said, and what the policy did.
    /// </summary>
    [PolicyCheck]
    public async Task AWrongExpectationIsADisagreementNotAnError()
    {
        // Policy 3 permits a trade only within 30s of a price. A trade with no price before it is
        // denied -- and this table says it is allowed.
        const string rows = """
            row table: a trade with nothing before it
            @0  request  execute_trade  { }  ALLOW
            """;

        var tools = new PolicyTools(projectRoot: Repo);
        var r = await tools.CheckDecisionTableAsync(
            Path.Combine("examples", "aws1", "03-data-freshness.dw"), rows: rows, engine: false);

        Assert.True(r.Answered, r.Error);
        var d = r.Result!.Value.GetProperty("rows")[0].GetProperty("decisions")[0];
        Assert.False(d.GetProperty("agrees").GetBoolean());
        Assert.Equal("ALLOW", d.GetProperty("expected").GetString());
        Assert.Equal("DENY", d.GetProperty("model").GetString());
    }

    /// <summary>
    /// A row the gateway could never have recorded -- a response to a request the table says is
    /// denied -- is refused before anything is checked. Checking it would blame the policy for a slip
    /// in the table.
    /// </summary>
    [PolicyCheck]
    public async Task AnImpossibleHistoryIsMalformedNotChecked()
    {
        const string rows = """
            row table: a price that was denied, and yet completed
            @0  request  get_market_price  { }  DENY
            @1  response get_market_price  { } -> { }
            @5  request  execute_trade     { }  ALLOW
            """;

        var tools = new PolicyTools(projectRoot: Repo);
        var r = await tools.CheckDecisionTableAsync(
            Path.Combine("examples", "aws1", "03-data-freshness.dw"), rows: rows, engine: false);

        Assert.False(r.Answered);
        Assert.Contains("malformed", r.Error);
        Assert.Contains("DENIES", r.Error);
    }

    /// <summary>One table at a time: a path and inline rows together is refused, not merged.</summary>
    [Fact]
    public async Task ATableAndRowsTogetherAreRefused()
    {
        var tools = new PolicyTools(projectRoot: Repo);
        var r = await tools.CheckDecisionTableAsync("p.dw", table: "t.table", rows: "row x: y");

        Assert.False(r.Answered);
        Assert.Contains("exactly one", r.Error);
    }

    #endregion

    #region Fields

    static readonly string Repo = PythonProcess.FindRoot().IsSuccess
        ? PythonProcess.FindRoot().Value : Directory.GetCurrentDirectory();

    #endregion
}
