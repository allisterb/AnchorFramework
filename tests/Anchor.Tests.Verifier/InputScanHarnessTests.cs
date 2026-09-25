namespace Anchor.Tests.TLAPlus;

/// <summary>
/// The input scanner: hidden text, adversarial prompts and markup in a policy are caught before a
/// model, a browser or a terminal is shown them, and ordinary policies are left alone.
/// </summary>
/// <remarks>
/// <para>
/// Anchor is run on a policy <b>because</b> someone does not trust it, and that policy's text
/// reaches a model in <c>auto</c>, <c>hitl</c> and the audit's questions, a browser in
/// <c>findings.html</c>, and a terminal in every verb. None of what this looks for is a parse error,
/// so nothing else in the suite would notice it.
/// </para>
/// <para>
/// Its own class because it takes milliseconds: xunit runs a class as one collection, and a fast
/// test parked in a slow class waits for that class's floor.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why this may report as skipped.
/// </remarks>
public class InputScanHarnessTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// Every attack is caught at its severity and in its context, and every ordinary text is not.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <b>Both halves are asserted with equal weight.</b> A miss lets hidden text reach a model; a
    /// false positive teaches people to pass <c>--allow-flagged-input</c> without reading, which is
    /// a miss with extra steps. So each attack has a benign neighbour that must stay clean:
    /// <c>system:</c> the chat role and <c>system:</c> the AgentCore context field, "the reviewer
    /// must" and "the agent must" — the first of each pair is an attack and the second is how
    /// requirements in this domain are written.
    /// </para>
    /// <para>
    /// The evasions are the point of several cases: a Cyrillic <c>о</c> inside "ignore", a
    /// zero-width space splitting "previous", fullwidth <c>＜script＞</c>, and a bidi override
    /// written as a <c>\u{202E}</c> escape so the file looks clean while the string's value is not.
    /// </para>
    /// </remarks>
    [PythonHarness("input_scan.py")]
    public async Task HiddenTextAndAdversarialPromptsAreCaughtAndOrdinaryPoliciesAreNot()
    {
        var run = await PythonHarness.RunAsync("tests/strands/input_scan.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("ok   trojan-source bidi in a string", run.Output);
        Assert.Contains("ok   cyrillic a in an action name", run.Output);
        Assert.Contains("ok   bidi written as an escape", run.Output);
        Assert.Contains("ok   injection with a cyrillic o", run.Output);
        Assert.Contains("ok   base64 carrying an instruction", run.Output);
        Assert.Contains("ok   a schema field named system", run.Output);
        Assert.Contains("ok   a requirement about the agent", run.Output);

        // The report prints the lines it flags. Printing a raw ESC would run the very terminal
        // sequence it had just reported.
        Assert.Contains("ok   a flagged ESC is printed as <U+001B>, never as itself", run.Output);

        // The gate refuses by default; the override is explicit and nothing else gets through.
        Assert.Contains("ok   a high finding refuses, with no verdict (2)", run.Output);

        // The false-positive test that matters: the repository's own policies and modules.
        Assert.Contains("ok   tests/policies", run.Output);

        Assert.DoesNotContain("MISS", run.Output);
        Assert.DoesNotContain("FP  ", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    #endregion
}
