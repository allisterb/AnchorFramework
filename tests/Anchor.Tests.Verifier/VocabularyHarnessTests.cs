namespace Anchor.Tests.TLAPlus;

/// <summary>
/// What a policy&#39;s values become in the model: the domains a field ranges over, glob patterns,
/// address ranges, and the scope a temporal predicate can see. Each of these is a place where a
/// modelling shortcut would produce an answer about a policy nobody wrote.
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
/// This class measured <b>185s</b> in the last full run, its slowest test being
/// <c>IpRangeContainmentMatchesTheStandard</c> at 44s. Those are wall clock UNDER
/// CONTENTION — five other classes are running — so they are 2-3x what the same test
/// takes alone, and they predate the checker memo. The 508s split above is older still.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why any of these may report as skipped.
/// </remarks>
public class VocabularyHarnessTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// Each field carries its own domain, derived from the literals the policy names — so a policy
    /// reading several fields can be explored, and a field's <em>type</em> is not assumed.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Both halves fix a real limit. One shared domain moved every field together, so a policy
    /// reading two of them had to be refused rather than under-explored — <b>34%</b> of the
    /// parseable corpus. And every output field was modelled as a boolean, so a gate on a string
    /// output could never match and was reported <b>VACUOUS</b>: a working permit declared inert,
    /// which is the one wrong answer this tool must not give. Eight output binds in Dogwood's own
    /// corpus compare against a string.
    /// </para>
    /// <para>
    /// Mutation-checked: ignoring the literals a policy names brings the false VACUOUS straight
    /// back, which is what this test's <c>live</c> assertion catches.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task FieldDomainsComeFromTheLiteralsThePolicyNames()
    {
        var strings = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/string_output.dw");

        Assert.True(strings.ExitCode == 0, strings.Output);
        Assert.Matches(@"permit #2\s+action == Read\s+live", strings.Output);
        Assert.DoesNotMatch(@"permit #\d+\s+action == \w+\s+VACUOUS", strings.Output);

        // The docs' trading example reads an input field and an output field, and joins on the
        // input — so it only works if the two move independently.
        var trading = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/docs_trading.dw");

        Assert.True(trading.ExitCode == 0, trading.Output);
        Assert.Matches(@"permit #2\s+action == SellShares\s+live", trading.Output);
    }

    /// <summary>
    /// Cedar's <c>like</c> is evaluated by TLC, and a field carrying two patterns gets a value
    /// satisfying both — or a refusal, never a guess.
    /// </summary>
    /// <remarks>
    /// <para>
    /// A TLA+ string is a sequence, and TLC's <c>Sequences</c> implementation supports
    /// <c>Len</c>, <c>\o</c> and <c>SubSeq</c> on one. What it does not support is applying a
    /// string as a function — <c>s[1]</c> fails — so <c>LikeMatches</c> reads a character as
    /// <c>SubSeq(s, i, i)</c>. The pattern semantics therefore live in the spec, like every other
    /// operator's, rather than in the harness.
    /// </para>
    /// <para>
    /// The first assertion guards a false <b>VACUOUS</b>, the same species as
    /// <see cref="FieldDomainsComeFromTheLiteralsThePolicyNames"/>: the vacuity checker invents
    /// the values a field can take, so unless it invents one the pattern matches, the guard can
    /// never be true and a working permit is declared inert.
    /// </para>
    /// <para>
    /// The second is the case that needs a value satisfying two patterns at once.
    /// <c>stock like "A*" &amp;&amp; stock like "*L"</c> is satisfied by <c>"AAPL"</c>, but the
    /// per-pattern witnesses are <c>"A"</c> and <c>"L"</c> and neither satisfies the other. Since
    /// TLC judges the real pattern, an invented candidate can never make a policy falsely live —
    /// only fail to be found — so the checker constructs one and this stays <c>live</c>.
    /// </para>
    /// <para>
    /// The third is where that search comes up empty. Nothing starts with both A and B, so
    /// VACUOUS is the <i>correct</i> verdict and the checker still refuses: at that point "no such
    /// string exists" is indistinguishable from "the search was not clever enough", and reporting
    /// VACUOUS on a hunch tells someone to delete a rule.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task LikePatternsAreEvaluatedByTheModel()
    {
        var one = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/like_prefix.dw");

        Assert.True(one.ExitCode == 0, one.Output);
        Assert.Matches(@"permit #1\s+action == SellShares\s+live", one.Output);
        Assert.DoesNotMatch(@"permit #\d+\s+action == \w+\s+VACUOUS", one.Output);

        // Two patterns, jointly satisfiable: a witness is constructed and the permit stays live.
        var two = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/like_two_patterns.dw");

        Assert.True(two.ExitCode == 0, two.Output);
        Assert.Matches(@"permit #1\s+action == SellShares\s+live", two.Output);
        Assert.DoesNotMatch(@"permit #\d+\s+action == \w+\s+VACUOUS", two.Output);

        // Two patterns no string satisfies: refused, and specifically not reported vacuous.
        var none = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/like_impossible.dw");

        Assert.Equal(2, none.ExitCode);
        Assert.Contains("`like` patterns at once", none.Output);
        Assert.DoesNotMatch(@"permit #\d+\s+action == \w+\s+VACUOUS", none.Output);
    }

    /// <summary>
    /// Cedar's <c>ipaddr</c>: CIDR containment against Python's <c>ipaddress</c>, and a property
    /// that catches a prefix-length slip.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <b>This is the one part of the Dogwood model with no Dogwood oracle.</b> <c>ip(</c> and
    /// <c>isInRange</c> appear in zero <c>.dw</c> files across the whole tree — no corpus case, no
    /// example, no test — and <c>dogwood replay</c> cannot supply an address at all: its log value
    /// parser has no case for an extension value, so <c>ip("10.1.2.3")</c> in a trace becomes the
    /// <i>string</i> <c>ip("10.1.2.3")</c>, the extension call fails on the wrong type, and the
    /// policy silently does not apply. A forbid on <c>10.0.0.0/8</c> replays <c>10.1.2.3</c> as
    /// ALLOW.
    /// </para>
    /// <para>
    /// So the arithmetic is differentially tested against <c>ipaddress</c> instead — two
    /// independent implementations of one standard — and that is all it establishes. How a real
    /// deployment feeds an address in is exactly what Dogwood's own tooling cannot exercise.
    /// </para>
    /// <para>
    /// An address is four octets rather than a 32-bit number, and that is forced: TLC works in
    /// Java ints and stops at 2147483647, so <c>208.4.4.0</c> — 3489924096 — is not a value it can
    /// hold. Every octet is 0..255.
    /// </para>
    /// <para>
    /// The property half is the payoff. <c>firewall_ip_narrow.dw</c> writes <c>/9</c> where
    /// <c>/8</c> was meant, leaving the upper half of the range unblocked; every built-in check
    /// passes it — both rules fire, neither is redundant — and a spot check on 10.1.2.3 looks
    /// fine. The property names <c>10.255.255.255</c>.
    /// </para>
    /// </remarks>
    [PythonHarness("ip_differential.py")]
    public async Task IpRangeContainmentMatchesTheStandard()
    {
        var diff = await PythonHarness.RunAsync("tests/strands/ip_differential.py");

        Assert.True(diff.ExitCode == 0, diff.Output);
        Assert.Contains("AGREE on every pair", diff.Output);
        Assert.DoesNotContain("DISAGREE", diff.Output);

        // The claim holds on the policy that means what it says.
        var good = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall_ip.dw",
            "--property", "tests/policies/firewall_ip.tla");

        Assert.True(good.ExitCode == 0, good.Output);
        Assert.Contains("every claim holds", good.Output);

        // A prefix-length slip that every derivable check passes.
        var narrow = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall_ip_narrow.dw",
            "--property", "tests/policies/firewall_ip.tla");

        Assert.Equal(1, narrow.ExitCode);
        Assert.Contains("BlockedRangeIsRefused", narrow.Output);
        Assert.Contains("10, 255, 255, 255", narrow.Output);

        var builtin = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall_ip_narrow.dw");

        Assert.True(builtin.ExitCode == 0, builtin.Output);
        Assert.Contains("every rule is load-bearing", builtin.Output);
    }

    /// <summary>
    /// A scope bind does not crash the checker, and <c>--event-schema</c> reaches the model.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>callerPrincipal: principal</c> is the ordinary way a policy says "the same principal did
    /// it", and it used to kill TLC outright: the synthesized events carried no <c>session</c>
    /// field, which <c>BindHolds</c> reads for every scope bind, so the run died with
    /// <c>Attempted to select nonexistent field "session"</c>. Latent because not one fixture used
    /// a scope bind — every policy here joined on payload fields instead — so it surfaced only
    /// when event schemas were wired in.
    /// </para>
    /// <para>
    /// The second half asserts the checker states which reading produced its answers. Every verdict
    /// it had ever printed assumed the <b>unpinned</b> posture while the shipped default is
    /// <c>pinned</c>, and it said nothing about that. The default is now Dogwood's own, and it
    /// still says so: a default the reader does not know was chosen for them is a choice they
    /// cannot question.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task ScopeBindsWorkAndTheSchemaPostureIsStated()
    {
        var bare = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/scope_bind.dw");

        Assert.True(bare.ExitCode == 0, bare.Output);
        Assert.Matches(@"permit #1\s+action == Trade\s+live", bare.Output);
        Assert.DoesNotContain("nonexistent field", bare.Output);

        // Without a schema it must say so — the answers are under Dogwood's default, pinned.
        Assert.Contains("uses Dogwood's own default", bare.Output);
        Assert.Contains("callerPrincipal pinned", bare.Output);

        // With one, it names the partition the deployment imposes.
        var pinned = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/scope_bind.dw",
            "--event-schema",
            "ext/dogwood/dogwood-language/configuration/event-schemas/pinned.dwschema");

        Assert.True(pinned.ExitCode == 0, pinned.Output);
        Assert.Contains("partitioned by principal", pinned.Output);
        Assert.Matches(@"permit #1\s+action == Trade\s+live", pinned.Output);
    }

    /// <summary>
    /// <c>RotationPolicies.tla</c> is generated from the <c>.dw</c> sources, so it can go stale.
    /// This regenerates and compares.
    /// </summary>
    /// <remarks>
    /// The generated module is checked in, which is what lets the spec tests run in CI without a
    /// venv — but a checked-in generated file is a copy, and a copy drifts. A <c>.dw</c> edit that
    /// was never carried through would leave <c>SessionRotation</c> quietly checking the previous
    /// policy while its own source file says something else.
    /// </remarks>
    [PythonHarness("dw_to_tla.py")]
    public async Task GeneratedRotationPoliciesAreUpToDate()
    {
        var run = await PythonHarness.RunAsync("src/translator/dw_to_tla.py", "--check");
        Assert.True(run.ExitCode == 0, run.Output);
        Assert.Contains("up to date", run.Output);
    }

    /// <summary>
    /// A literal too large for TLC is <b>refused by name</b>, not left to fail inside the model
    /// checker.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Cedar's <c>Long</c> runs to 2^63-1 and a budget cap written in cents reaches nine figures
    /// without anyone thinking about it. TLA+ integers are unbounded — this is <b>TLC's</b> limit,
    /// not the language's: it holds them in a Java int and reserves <c>Integer.MAX_VALUE</c>, so
    /// the largest literal it accepts is 2147483646. Measured, not assumed: 2147483646 checks and
    /// 2147483647 does not.
    /// </para>
    /// <para>
    /// What this pins is the <i>shape</i> of the failure. Unrefused, it arrives as
    /// <c>Error: TLC can't handle a number this big.</c> followed by the bare number, from a run
    /// naming neither the policy nor the field, at a point where a reader has no reason to suspect
    /// the literal. The house rule is to refuse and say which construct is responsible — the
    /// policy is valid, and it is the checker that cannot take it.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task ALiteralTooBigForTlcIsRefusedByName()
    {
        var run = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/long_overflow.dw");

        // 2 is "no verdict", which is what a refusal is. Never 0, which would report a policy
        // nobody checked as a policy with nothing wrong with it.
        Assert.True(run.ExitCode == 2, run.Output);
        Assert.Contains("outside the modelled subset", run.Output);
        Assert.Contains("3000000000", run.Output);
        Assert.Contains("2147483646", run.Output);

        // The raw TLC error must NOT be what the reader sees.
        Assert.DoesNotContain("TLC can't handle a number this big", run.Output);
    }

    /// <summary>
    /// A field's domain carries a value on <b>each side</b> of its literals, so every comparison
    /// operator has a witness — not just <c>==</c> and <c>&gt;</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The domain is the literals a policy names plus values it does not, so that matching and
    /// not-matching both stay reachable. The extra value used to be only <i>above</i> the largest
    /// literal, which leaves <c>&lt;</c> and <c>&lt;=</c> with nothing that satisfies them: the
    /// domain for <c>cost</c> below was <c>{25000, 25001}</c>, and neither is less than 25000.
    /// </para>
    /// <para>
    /// So an ordinary <c>context.input.cost &lt; 25000</c> was reported <b>VACUOUS</b> — a working
    /// permit declared dead, and the advice that follows a VACUOUS verdict is to delete the rule.
    /// That is the one wrong answer this checker must not give, and it is the same shape as the
    /// false VACUOUS that <c>FieldDomainsComeFromTheLiteralsThePolicyNames</c> guards from the
    /// other direction.
    /// </para>
    /// <para>
    /// It survived because every fixture that would have caught it compared for EQUALITY. Found by
    /// running the published policies from AWS's temporal-policies article, one of which gates on
    /// <c>cost &lt; 25000</c>.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task OrderingComparisonsHaveAWitnessInTheDomain()
    {
        var run = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/ordering_live.dw");

        Assert.True(run.ExitCode == 0, run.Output);
        Assert.Contains("live", run.Output);
        Assert.DoesNotContain("VACUOUS", run.Output);
    }

    /// <summary>
    /// The wall-clock <b>time of day</b> — <c>context.system.now.toTime()</c> — is modelled, and
    /// modelled well enough that an impossible window is caught.
    /// </summary>
    /// <remarks>
    /// <para>
    /// "Business hours only" is a whole class of published policy, and the clock is not determined
    /// by the trace: it is a value the request carries and the policy reads. So it is modelled as a
    /// request field, and gets a field's domain — the values the policy names plus ones either side
    /// — which is what makes both "inside the window" and "outside" reachable. Cedar counts a
    /// duration in milliseconds and so does the model.
    /// </para>
    /// <para>
    /// <b>The second half is the one that matters.</b> A model that admitted the clock but did not
    /// EVALUATE it would report both fixtures live and they would be indistinguishable. The
    /// backwards window — after 17:00 and before 09:00 — must come back VACUOUS.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task TheWallClockTimeOfDayIsModelledAndEvaluated()
    {
        var real = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/business_hours.dw");

        Assert.True(real.ExitCode == 0, real.Output);
        Assert.Contains("live", real.Output);
        Assert.DoesNotContain("VACUOUS", real.Output);

        // Backwards window: no time of day satisfies it, and saying so is what proves the clock is
        // a value the checker reasons about rather than one it merely accepts.
        var impossible = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/business_hours_impossible.dw");

        Assert.True(impossible.ExitCode == 0, impossible.Output);
        Assert.Contains("VACUOUS", impossible.Output);
    }

    /// <summary>
    /// A policy that is not valid Dogwood is reported as <b>broken</b>, not as unmodelled — and
    /// never as a clean result.
    /// </summary>
    /// <remarks>
    /// <para>
    /// This checker reads a SUBSET of Dogwood, so a refusal carries two possible meanings under one
    /// message: the construct is outside the subset, or the file is broken. Those need opposite
    /// responses — one is a limitation to work around, the other is a bug to go and fix — and our
    /// own parser cannot tell them apart, because it is the thing whose coverage is in question.
    /// </para>
    /// <para>
    /// The reference implementation settles it. <c>--syntax</c> asks first and stops; and on the
    /// refusal path it is consulted anyway, because by then the run has already failed and 35ms is
    /// nothing against telling somebody the wrong thing about why. <b>Exit 2 either way</b>: a
    /// policy that does not parse has not been checked, and 0 would be a clean bill of health for a
    /// file nobody could read.
    /// </para>
    /// <para>
    /// The fixture is the mutual-exclusion policy from AWS's temporal-policies article, which is
    /// printed with a predicate missing its <c>::kind</c> segment. Skipped when the binary is not
    /// built — the checker does not need it, which is why the skip is not a failure.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py", RequiresExecutable = "ext/dogwood/target/release/dogwood")]
    public async Task APolicyThatDoesNotParseIsReportedAsBrokenNotAsUnmodelled()
    {
        var asked = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/syntax_broken.dw", "--syntax");

        Assert.Equal(2, asked.ExitCode);
        Assert.Contains("SYNTAX ERROR", asked.Output);
        Assert.Contains("Nothing below was checked", asked.Output);
        // The engine's own diagnostic, pointing at the token rather than at a token index.
        Assert.Contains("unexpected token", asked.Output);

        // And without the flag: our refusal stands, with the engine's second opinion beneath it.
        var unasked = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/syntax_broken.dw");

        Assert.Equal(2, unasked.ExitCode);
        Assert.Contains("outside the modelled subset", unasked.Output);
        Assert.Contains("NOT VALID DOGWOOD EITHER", unasked.Output);

        // A policy that DOES parse must draw no such comment — a second opinion on a healthy file
        // is noise, and would train a reader to ignore it on the file that needs it.
        var fine = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/business_hours.dw", "--syntax");

        Assert.Equal(0, fine.ExitCode);
        Assert.Contains("parses, per the reference implementation", fine.Output);
        Assert.DoesNotContain("NOT VALID DOGWOOD", fine.Output);
    }

    /// <summary>
    /// An aggregate binder ranges over the scalars the <b>trace</b> carries, not only the generated
    /// value domain.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>sum a for (a: Long). where (… { input.amount: a })</c> binds <c>a</c> by matching events.
    /// A value present in the trace and absent from the generated domain was silently skipped, so
    /// the total came out <i>smaller</i> rather than unknown — a wrong verdict with no symptom, in
    /// the one construct whose whole purpose is to add things up.
    /// </para>
    /// <para>
    /// It never showed on the built-in questions, whose traces are assembled FROM the domain, so
    /// every value in them is in it already. It showed on a property module, which builds its own
    /// session — and being able to state a claim about values the policy never names is precisely
    /// why <c>PolicyUnderTest</c> offers no <c>Inputs</c>.
    /// </para>
    /// <para>
    /// Found by running a published policy: AWS's cumulative transfer cap, where a $60,000 attempt
    /// against a generated domain of <c>{1, 2}</c> summed to nothing, so a $50,000 cap was never
    /// reached and the model said ALLOW where the engine said DENY.
    /// </para>
    /// <para>
    /// <b>Both halves are asserted.</b> A model that summed nothing would pass
    /// <c>UnderTheCapIsAllowed</c> and fail <c>OverTheCapIsRefused</c>; one that over-counted would
    /// do the reverse. Verified to fail with the fix reverted.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task AnAggregateSeesTheValuesTheTraceCarries()
    {
        var run = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/aggregate_cap.dw",
            "--property", "tests/policies/aggregate_cap.tla");

        Assert.True(run.ExitCode == 0, run.Output);
        Assert.Contains("every claim holds", run.Output);
        Assert.DoesNotContain("BROKEN", run.Output);
    }

    #endregion
}
