namespace Anchor.Tests.TLAPlus;

/// <summary>
/// A JVM the checker starts dies with the checker, however the checker ends.
/// </summary>
/// <remarks>
/// <para>
/// It did not. On Windows the venv's <c>python.exe</c> is a launcher with the real interpreter as its
/// child, and <c>Process.Kill(entireProcessTree: true)</c> kills the root first: the launcher's job
/// takes the interpreter at once, and the walk for its children then finds nothing to walk under. A
/// checker that hit <c>--timeout</c> on aws1's 12-rule policy set left TLC running for fifteen hours.
/// <c>src/translator/tlc.py</c> now binds every JVM to a kill-on-close job of its own.
/// </para>
/// <para>
/// Windows only, because only there is the venv's python a launcher; elsewhere the harness says
/// SKIPPED and this accepts it. The harness carries its own control -- a plain child that DOES
/// survive -- so a pass is not the absence of a bug it could not have seen.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why this may report as skipped.
/// </remarks>
public class ProcessLifetimeHarnessTests : TestsRuntime
{
    #region Methods

    [PythonHarness("tlc_lifetime.py")]
    public async Task AJvmTheCheckerStartsDiesWithTheChecker()
    {
        var run = await PythonHarness.RunAsync("tests/strands/tlc_lifetime.py");
        Assert.True(run.ExitCode == 0, run.Output);

        if (!OperatingSystem.IsWindows())
        {
            Assert.Contains("SKIPPED", run.Output);
            return;
        }

        Assert.Contains("ok    the control: a plain Popen child outlives its venv-launched interpreter", run.Output);
        Assert.Contains("ok    a bound_popen child dies with it", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    #endregion
}
