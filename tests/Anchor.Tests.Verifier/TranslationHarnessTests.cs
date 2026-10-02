namespace Anchor.Tests.TLAPlus;

/// <summary>
/// Differential harnesses: our reading of somebody else&#39;s language, checked against their own
/// implementation. These are the tests that make every verdict downstream mean anything — a model
/// that disagrees with the engine is a model whose findings are about nothing.
/// </summary>
/// <remarks>
/// <para>
/// One of six classes the harness tests are split across. <b>xunit parallelises across
/// collections, and a class with no <c>[Collection]</c> attribute is its own collection</b> — so
/// tests in one class run strictly one after another, and the suite's wall clock is the slowest
/// single class. Measured: as one class these took 507s serially while seven cores idled. The
/// split is balanced by measured duration, not by count, and the floor is the longest single test.
/// </para>
/// <para>
/// This class measured <b>335s</b> in the last full run, its slowest test being
/// <c>GraphTranslatorAgreesWithTheSdk</c> at 112s. Those are wall clock UNDER
/// CONTENTION — five other classes are running — so they are 2-3x what the same test
/// takes alone, and they predate the checker memo. The 508s split above is older still.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why any of these may report as skipped.
/// </remarks>
public class TranslationHarnessTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// Strands decides readiness per edge with OR semantics, so an unguarded join starts before all
    /// its parents are done. Both halves are pinned: unguarded graphs must violate HP10 and admit
    /// the join twice in the real SDK; guarded with <c>all_complete</c> they must verify and admit
    /// it once.
    /// </summary>
    [PythonHarness("graph_to_tla.py", "strands")]
    public async Task GraphTranslatorAgreesWithTheSdk()
    {
        var run = await PythonHarness.RunAsync("tests/strands/graph_to_tla.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("all scenarios matched expectation", run.Output);

        // Both colours, or the comparison proves nothing.
        Assert.Contains("HP10 + termination: VIOLATED", run.Output);
        Assert.Contains("HP10 + termination: HOLD", run.Output);

        // The SDK side of the same red/green. Keyed on how many times the join is admitted rather
        // than on execution order: the batch runs concurrently, so the order varies between runs.
        Assert.Contains("C ran 2x", run.Output);
        Assert.Contains("C ran 1x", run.Output);

        // The cross-model matrix, and specifically the two rows where the models disagree. Both
        // are findings in their own right and both are easy to lose to a well-meaning edit.
        Assert.DoesNotContain("! unexpected", run.Output);

        // DependencyDAG over-approximates: no batches, so it reports a violation the executor
        // cannot produce. Losing this row would mean the diamond had started failing for real.
        Assert.Matches(@"docs diamond, unguarded\s+VIOLATED\s+HOLD", run.Output);

        // And the other direction: the paper's orchestrator cancels what it cannot admit, so it
        // satisfies the property honestly, while Strands stops and reports success with a node
        // never run. A failure class DependencyDAG cannot express.
        Assert.Matches(@"router, opaque conditions\s+HOLD\s+VIOLATED", run.Output);

        // Each StrandsGraph finding attributed to the one shape that causes it. The combined
        // config cannot do this — TLC stops at the first violation, so on the skew graph
        // RunsAtMostOnce is masked by HP10 — which is why these were checked one at a time and
        // why they are pinned here rather than left as a table in a README.
        Assert.Matches(@"NoSilentSkip\s+ok\s+ok\s+VIOLATED", run.Output);
        Assert.Matches(@"HP10\s+ok\s+VIOLATED\s+ok", run.Output);
        Assert.Matches(@"RunsAtMostOnce\s+ok\s+VIOLATED\s+ok", run.Output);
    }

    /// <summary>
    /// Our semantics against the real Dogwood engine, on traces we construct — specifically ones
    /// containing the <c>error</c> event kind, which appears in <b>zero</b> policies and
    /// <b>zero</b> traces across all 521 corpus cases.
    /// </summary>
    /// <remarks>
    /// The corpus validates a lot, but only over traces Amazon happened to record. `error` is the
    /// kind AgentCore uses for a denied action, and it is what both TemporalPolicy findings rest
    /// on: a permit gated on <c>::response</c> goes vacuous when its dependency is forbidden, and
    /// the same rule written against <c>::request</c> does not. The built binary is a live oracle
    /// and will judge any trace, so those claims are now executed rather than only modelled.
    /// <para>
    /// Skipped unless the binary has been built — it is not in the repo. Mutation-checked: making
    /// our <c>Matches</c> ignore the event kind, or treat <c>error</c> as <c>response</c>, each
    /// turns this red.
    /// </para>
    /// </remarks>
    [PythonHarness("dogwood_replay.py",
                   RequiresExecutable = "ext/dogwood/target/release/dogwood")]
    public async Task DogwoodSemanticsAgreeWithTheEngineOnErrorEvents()
    {
        var run = await PythonHarness.RunAsync("tests/strands/dogwood_replay.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("agrees with the Dogwood engine on every scenario", run.Output);
        Assert.DoesNotContain("MODEL DISAGREES", run.Output);

        // The finding itself, not just that the scenarios ran: the same denied approval opens a
        // request-gate and not a response-gate.
        Assert.Contains("request-gate, approval DENIED", run.Output);
        Assert.Matches(@"response-gate, approval DENIED\s+@1=DENY, @3=DENY", run.Output);

        // The second finding: one policy, one trace, two shipped event schemas, opposite verdicts.
        // A universal pin partitions the history a temporal predicate can see, and the policy text
        // says nothing about it — so asserting BOTH lines is the point. Either alone would pass
        // for a model that ignored the schema entirely.
        Assert.Matches(@"OTHER session, session-pinned\s+@1=DENY, @3=DENY", run.Output);
        Assert.Matches(@"OTHER session, unpinned\s+@1=DENY, @3=ALLOW", run.Output);
        Assert.Matches(@"request-gate, approval DENIED\s+@1=DENY, @3=ALLOW", run.Output);
    }

    /// <summary>
    /// Anchor's own property-authoring pipeline, wired as the <c>Graph</c> that would run it
    /// multi-agent and checked by Anchor. Three honest wirings, each unsatisfactory in its own way,
    /// and the point is that all three rows stay as they are: a gated pipeline reports success
    /// having said nothing, routing the rejection breaks two more properties, and moving the gates
    /// inside the nodes clears everything by removing what was being checked.
    /// </summary>
    [PythonHarness("anchor_workflow.py", "strands")]
    public async Task AnchorsOwnPipelineIsCheckedByAnchor()
    {
        var run = await PythonHarness.RunAsync("tests/strands/anchor_workflow.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("all expectations matched", run.Output);

        // The separation the whole graph exists to express, and it is the SDK that enforces it:
        // one Agent instance cannot be both the drafter and the answerer.
        Assert.Contains("Duplicate node instance detected", run.Output);

        // Every row, both colours, over pipeline / always_report / gated / sequential.
        Assert.Matches(@"NoSilentSkip\s+VIOLATED\s+VIOLATED\s+VIOLATED\s+ok", run.Output);
        Assert.Matches(@"HP10\s+ok\s+VIOLATED\s+VIOLATED\s+ok", run.Output);
        Assert.Matches(@"Terminates\s+ok\s+ok\s+ok\s+ok", run.Output);

        // THE ONE THE verdict() COMBINATOR BOUGHT. `gated` is `always_report` with each gate's two
        // arms declared as one decision — same shape, same Python, same ignorance of what either
        // gate will decide. Declaring the pair is the only difference between these two cells.
        Assert.Matches(@"RunsAtMostOnce\s+ok\s+VIOLATED\s+ok\s+ok", run.Output);

        // And the author's own claim, which no property derivable from the graph can state:
        // however the gates decide, the run reports. Both colours, on graphs that differ only in
        // whether the arms were declared.
        Assert.Matches(@"always_report\s+VIOLATED", run.Output);
        Assert.Matches(@"gated\s+HOLD", run.Output);

        // The gate conditions read a node's OUTPUT, which no status combinator can express, so
        // they stay free choices. If this ever reads 0 the gates stopped being modelled as unknown
        // and the checks above would be proving something easier than they claim.
        Assert.Contains("not modelled: 2", run.Output);
        Assert.Contains("not modelled: 4", run.Output);

        // verdict()'s own semantics: a gate that CRASHED did not reject, and the rejection arm
        // must not fire on its behalf.
        Assert.Matches(@"failed\s+passed=False\s+rejected=False", run.Output);
        Assert.Contains("both arms wired -> two exclusive pairs     ok", run.Output);
    }

    /// <summary>
    /// Every checked-in property under both event-schema readings — global-trace, and the
    /// per-principal partitioning Dogwood applies by default.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Two things are at stake. Every finding we publish is scoped to a reading, and one that
    /// holds under only one of them is a weaker claim than it looks. And Anchor's own default with
    /// no schema was the <b>opposite</b> of Dogwood's until 0.1.3 — a verification tool whose
    /// default differs from the deployed default can report something that does not reproduce. It
    /// is now Dogwood's, pinned, and this holds it there.
    /// </para>
    /// <para>
    /// Runs <c>--quick</c>: the full sweep is 48 checker runs and about three and a half minutes,
    /// which is not worth paying per CI run while the answer keeps coming back the same. Drop the
    /// flag for the whole corpus.
    /// </para>
    /// </remarks>
    [PythonHarness("event_schema_readings.py", "strands")]
    public async Task FindingsDoNotDependOnTheEventSchemaReading()
    {
        var run = await PythonHarness.RunAsync("tests/strands/event_schema_readings.py", "--quick");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("all checks passed", run.Output);
        Assert.DoesNotContain("DIFFERS", run.Output);

        // The equivalence that lets --pinned exist without the submodule checked out.
        Assert.Contains("ok    --pinned agrees with the shipped pinned.dwschema", run.Output);
        Assert.Contains("ok    Anchor's no-schema default agrees with the shipped PINNED", run.Output);

        // The copies the witness replay hands the engine, which the container needs because it
        // carries the dogwood binary and not the tree those files come from.
        Assert.Contains("ok    the replay's pinned schema is Dogwood's pinned.dwschema", run.Output);
        Assert.Contains("ok    the replay's unpinned schema is Dogwood's unpinned.dwschema", run.Output);

        // The derived half must be MEASURED, not merely equal: a column of zeroes would agree for
        // the wrong reason, so at least one policy compared here carries a known defect.
        Assert.Contains("1:VACUOUS", run.Output);
    }

    /// <summary>
    /// An edge condition's TLA+ predicate has to mean what its Python does, or the annotation is the
    /// same silent-disagreement trap as a hand-written translator. The mutation matters most: a
    /// harness that cannot catch a deliberate mistranslation is checking nothing.
    /// </summary>
    [PythonHarness("condition_differential.py", "strands")]
    public async Task ConditionPredicatesAgreeWithTheirPython()
    {
        var run = await PythonHarness.RunAsync("tests/strands/condition_differential.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("matched expectation", run.Output);
        Assert.DoesNotContain("! expected", run.Output);

        // Sensitivity: the deliberately wrong predicate must still be caught.
        Assert.Contains("DISAGREE", run.Output);
        Assert.Matches(@"mistranslated.*DISAGREE", run.Output);
    }

    /// <summary>
    /// Our TLA+ reading of Dogwood's temporal operators — <c>formerly</c>, <c>previous</c> and
    /// <c>since</c>, combined with <c>&amp;&amp;</c> and <c>!</c> — against the reference
    /// implementation's own regression corpus, whose cases pair policies and traces with the
    /// verdicts their engine actually produced.
    /// </summary>
    /// <remarks>
    /// This closes the largest caveat on <c>specs/policy/TemporalPolicy</c>: that it modelled the
    /// documented rules with nothing checking the reading was right. Nothing is built or run from
    /// the Dogwood tree — the expected outputs are recorded, so the corpus is usable as data, and
    /// this stays inside the suite's no-network property.
    /// <para>
    /// The refusal count matters as much as the agreement count. A translator that quietly
    /// mishandles a construct produces a disagreement it cannot attribute, so anything outside the
    /// modelled subset is refused. It already caught one: a case whose <c>event.dwschema</c> pins
    /// <c>callerPrincipal</c> into every predicate, making the policy mean something its own text
    /// never says.
    /// </para>
    /// </remarks>
    [PythonHarness("dogwood_differential.py",
                   RequiresPath = "ext/dogwood/dogwood-language/tests/passing/temporal_only/corpus")]
    public async Task DogwoodSemanticsAgreeWithTheReferenceCorpus()
    {
        var run = await PythonHarness.RunAsync("tests/strands/dogwood_differential.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("agrees with the reference", run.Output);
        Assert.DoesNotContain("DISAGREEMENT", run.Output);

        // Enough cases to be worth something. If the subset silently narrowed — a parser change
        // refusing more than it did — this notices rather than reporting a hollow success.
        var m = System.Text.RegularExpressions.Regex.Match(run.Output, @"checked\s+(\d+) \(trace");
        Assert.True(m.Success, run.Output);
        Assert.True(int.Parse(m.Groups[1].Value) >= 640,
                    $"only {m.Groups[1].Value} pairs checked\n{run.Output}");
    }

    /// <summary>
    /// Our reading against <b>AWS's own statement</b> of how AgentCore decides: the 28 worked
    /// temporal examples in the AgentCore guide, with their decision tables as the oracle.
    /// </summary>
    /// <remarks>
    /// Run <c>--stripped</c>, with the gateway scope and <c>eventResource</c> joins removed, because
    /// Anchor does not yet model AgentCore's event schema; with one gateway that removal changes no
    /// decision (<c>docs/agentcore.md</c>). The verbatim run is the target for modelling it, and
    /// refuses every case until then. Caught on its first run: the parser accepted only the
    /// corpus's parenthesised <c>exists</c> body, which refused all six of AWS's aggregates.
    /// </remarks>
    [PythonHarness("agentcore_conformance.py",
                   RequiresPath = "ext/dogwood/dogwood-language/configuration/event-schemas")]
    public async Task DogwoodSemanticsReproduceAgentCoreDecisionTables()
    {
        var run = await PythonHarness.RunAsync("tests/strands/agentcore_conformance.py", "--stripped");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("every example conforms", run.Output);
        Assert.DoesNotContain("DISAGREES", run.Output);
    }

    /// <summary>
    /// Our reading against Dogwood's own <b>documentation examples</b> — whole policies, rather
    /// than the unit corpus's one-construct-per-case.
    /// </summary>
    /// <remarks>
    /// <para>
    /// A different kind of evidence, and the one that answers "would this work on my policy". The
    /// unit corpus is written to test the engine construct by construct; these are written to show
    /// someone how to use the language, so they are closer to the population a real policy comes
    /// from. The coverage number is therefore the honest one, and it is lower.
    /// </para>
    /// <para>
    /// Two conventions differ from the unit corpus and both would silently misalign every verdict:
    /// the oracle is the CLI's <c>ALLOW</c>/<c>DENY</c> rather than <c>true</c>/<c>false</c>, and
    /// "time point N" counts <b>decisions</b> here where it indexes the whole trace there. The
    /// harness keys on the <c>@N</c> timestamp, which means the same thing in both.
    /// </para>
    /// <para>
    /// Asserted as a floor rather than an exact figure: widening the subset should move it up, and
    /// a drop means something regressed.
    /// </para>
    /// </remarks>
    [PythonHarness("dogwood_examples.py")]
    public async Task OurReadingAgreesWithDogwoodsOwnExamples()
    {
        var run = await PythonHarness.RunAsync("tests/strands/dogwood_examples.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("AGREE", run.Output);
        Assert.DoesNotContain("DISAGREE", run.Output);

        // The attribution check is only worth anything where the verdict does not already force
        // the answer, and most decisions here are single-policy, where it does. If that floor
        // ever reaches zero the check still prints AGREE while proving nothing.
        var attrib = System.Text.RegularExpressions.Regex.Match(
            run.Output, @"attribution checked on (\d+) decisions, of which (\d+)");
        Assert.True(attrib.Success, run.Output);
        Assert.True(int.Parse(attrib.Groups[2].Value) >= 8,
                    $"only {attrib.Groups[2].Value} decisions have an unforced attribution, so the "
                    + $"check is close to vacuous\n{run.Output}");

        // Enough examples to mean something. A silent narrowing — a parser change refusing more
        // than it did — would otherwise still report a hollow success.
        var m = System.Text.RegularExpressions.Regex.Match(run.Output, @"checked\s+(\d+) of (\d+)");
        Assert.True(m.Success, run.Output);
        Assert.True(int.Parse(m.Groups[1].Value) >= 37,
                    $"only {m.Groups[1].Value} examples translated\n{run.Output}");
    }

    /// <summary>
    /// The TLA+ model of Cedar against the real engine, over the whole finite request space.
    /// </summary>
    [PythonHarness("cedar_differential.py", "cedarpy")]
    public async Task CedarModelAgreesWithTheRealEngine()
    {
        var run = await PythonHarness.RunAsync("tests/strands/cedar_differential.py");
        Assert.True(run.ExitCode == 0, run.Output);
        Assert.Contains("AGREE on all", run.Output);
        Assert.DoesNotContain("DISAGREE", run.Output);
    }

    /// <summary>
    /// The <c>specs/strands/ToolExecutor</c> finding, against a <b>running agent</b> rather than
    /// against a reading of the SDK source.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Every other finding here is checked against something that can disagree — the Dogwood
    /// corpus, the built engine, the real Cedar bindings. That one was backed only by three lines
    /// of quoted dispatch logic, which is weaker evidence than it looked. This runs a real
    /// <c>Agent</c> with a scripted model that emits four tool uses in one turn, so the default
    /// <c>ConcurrentToolExecutor</c> genuinely spawns four tasks, and puts the same hook body
    /// through all three grains the spec models.
    /// </para>
    /// <para>
    /// The concurrency count is the load-bearing observation: a <c>def</c> callback never has more
    /// than <b>one</b> body in flight, so it cannot be interleaved, while the <c>async</c> ones
    /// have four. Without that, a green run would prove only that nothing happened to overlap —
    /// so the probe fails loudly if the batch never overlapped at all.
    /// </para>
    /// </remarks>
    [PythonHarness("tool_hook_probe.py", "strands")]
    public async Task RunningAgentBehavesAsTheToolExecutorSpecPredicts()
    {
        var run = await PythonHarness.RunAsync("tests/strands/tool_hook_probe.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.DoesNotContain("NOT WHAT THE SPEC PREDICTS", run.Output);

        // A synchronous hook cannot be interleaved: one body in flight, and the cap holds.
        Assert.Matches(@"synchronous hook\s+1\s+4\s+1\s+cap holds", run.Output);

        // An await AFTER the write is safe even though four bodies overlap — the counter still
        // serialises. "Async hooks are unsafe" would be too crude, and this is why.
        Assert.Matches(@"suspends AFTER the write\s+4\s+4\s+1\s+cap holds", run.Output);

        // An await BETWEEN read and write loses updates: a cap of one admits four calls, and the
        // counter ends at one. Both of the spec's properties fail, exactly as modelled.
        Assert.Matches(@"BETWEEN read and write\s+4\s+1\s+4\s+CAP EXCEEDED", run.Output);
    }

    /// <summary>
    /// Bug3 reaching the real SDK: several agents on one budget, with both ledgers. The reserving
    /// one stays inside the budget; the naive check-then-charge one does not.
    /// </summary>
    /// <remarks>
    /// Asserts the shape rather than the overspend figure. The race is an interleaving, and pinning
    /// an exact number would be pinning one instance of it.
    /// </remarks>
    [PythonHarness("shared_budget.py", "strands")]
    public async Task NaiveLedgerOverspendsTheSharedBudget()
    {
        var run = await PythonHarness.RunAsync("tests/strands/shared_budget.py");
        Assert.True(run.ExitCode == 0, run.Output);
        Assert.Contains("budget respected", run.Output);
        Assert.Contains("budget VIOLATED", run.Output);
    }

    #endregion
}
