namespace Anchor.Tests.TLAPlus;

/// <summary>
/// Text crosses every subprocess boundary as UTF-8: dogwood to Python, the checker to its caller,
/// and Python to TLC and back.
/// </summary>
/// <remarks>
/// <para>
/// A pipe's text is decoded with the locale unless told otherwise, and Windows' locale is cp1252.
/// Linux, and so CI and the container, never showed it: this is the test that would have. On
/// Windows, dogwood's box-drawn diagnostic came back as mojibake; relayed through the checker it
/// crashed a reader thread on byte 0x9d and the text was <b>lost</b> — a failure that reads as an
/// absence of output — and a non-ASCII string in a TLA+ module was read and printed back as cp1252.
/// </para>
/// <para>
/// Its own class because it is fast, a few seconds of one TLC run and two dogwood calls, and
/// parked in a slow class it would wait for that class's floor. Skipped when the dogwood binary is
/// not built: two of its three boundaries are dogwood's.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why this may report as skipped.
/// </remarks>
public class SubprocessEncodingHarnessTests : TestsRuntime
{
    #region Methods

    [PythonHarness("subprocess_utf8.py", RequiresExecutable = "ext/dogwood/target/release/dogwood")]
    public async Task TextCrossesEverySubprocessBoundaryAsUtf8()
    {
        var run = await PythonHarness.RunAsync("tests/strands/subprocess_utf8.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("ok    its diagnostic arrives with the box characters it was drawn with", run.Output);
        // The one that mattered: two pipes, and the text used to come back empty.
        Assert.Contains("ok    the relayed diagnostic survives two pipes", run.Output);
        Assert.Contains("ok    and nothing crashed on the way", run.Output);
        Assert.Contains("ok    and hands it back exactly", run.Output);

        Assert.DoesNotContain("FAIL", run.Output);
        Assert.DoesNotContain("SKIPPED", run.Output);
    }

    #endregion
}
