namespace Anchor.Tests.TLAPlus;

/// <summary>
/// The mistakes recorded drafts made are named precisely, and the drafter is given the rules.
/// </summary>
/// <remarks>
/// <para>
/// Drawn from about 45 recorded drafting attempts. Two static checks in preflight —
/// <c>author.tagged_orderings</c>, an ordering operator beside a tag constructor, and
/// <c>author.misplaced_fields</c>, a value in the half of an event the policy never reads it from —
/// and <c>author.diagnose</c>, which reads TLC's real error output and names the tagging mistake.
/// The rules are in the drafter's system prompt and in the vocabulary every agent is given.
/// </para>
/// <para>
/// Both static checks reject, so a false positive would throw away a good draft: real property
/// modules are put to them and none may be flagged. Its own class because it is fast.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why this may report as skipped.
/// </remarks>
public class DraftDiagnosticsHarnessTests : TestsRuntime
{
    #region Methods

    [PythonHarness("draft_diagnostics.py")]
    public async Task RecordedDraftingMistakesAreNamedAndRuled()
    {
        var run = await PythonHarness.RunAsync("tests/strands/draft_diagnostics.py");
        Assert.True(run.ExitCode == 0, run.Output);

        // Tagging.
        Assert.Contains("ok    flags `x <= Num(2500)`", run.Output);
        Assert.Contains("real property modules in the repo", run.Output);
        Assert.Contains("is diagnosed as: ordering operator", run.Output);
        Assert.Contains("ok    an unrelated TLC error gets no tagging diagnosis", run.Output);
        // Placement: the recorded draft is caught, and what must be left alone is.
        Assert.Contains("ok    the recorded draft is flagged: profile_id in the lookup's OUTPUT", run.Output);
        Assert.Contains("ok    a value echoed in both halves is left alone", run.Output);
        Assert.Contains("ok    a value the policy reads from neither half is left alone", run.Output);
        Assert.Contains("ok    no false alarm on examples/aws2/CumulativeCap.tla", run.Output);
        // The rules reach both kinds of agent.
        Assert.Contains("ok    the drafter's system prompt states the rules", run.Output);
        Assert.Contains("ok    the vocabulary's rules carry them to MCP agents too", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    #endregion
}
