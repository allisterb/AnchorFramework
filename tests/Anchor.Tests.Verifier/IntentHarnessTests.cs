namespace Anchor.Tests.TLAPlus;

/// <summary>
/// The intentional checks — what only the policy&#39;s author can state. A <c>--property</c> module
/// saying what the policy is supposed to mean, a comparison saying which direction an edit moved,
/// and the witness session each answer rests on.
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
/// This class measured <b>186s</b> in the last full run, its slowest test being
/// <c>TheAwsExampleFindsWhatOnlyIntentCanFind</c> at 81s. Those are wall clock UNDER
/// CONTENTION — five other classes are running — so they are 2-3x what the same test
/// takes alone, and they predate the checker memo. The 508s split above is older still.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why any of these may report as skipped.
/// </remarks>
public class IntentHarnessTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// The worked example under <c>examples/aws1</c>: AWS's published AgentCore temporal policies,
    /// verbatim, and the findings that only an <b>intentional</b> property can reach.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Pinned as a test because it is the project's headline claim and the most expensive thing to
    /// discover twice. The headline: deployed together, the article's policies allow a trade from an
    /// EMPTY trajectory, and the corrected set in <c>fixed/</c> does not. Both directions are
    /// asserted, because a claim that broke on every policy set would be about the claim.
    /// </para>
    /// <para>
    /// No rule-by-rule run of the whole set here. Exhaustively, at the 4 attempts a trade needs
    /// under the fixed set, it does not finish -- that run is what used to time this suite out.
    /// The article's own decision tables, checked in
    /// <see cref="TranslationHarnessTests.TheBlogPostsPoliciesAreCheckedAgainstItsOwnTables"/>, are
    /// the stronger control.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task TheAwsExampleFindsWhatOnlyIntentCanFind()
    {
        // The headline, on the set as published: a trade with nothing before it is allowed.
        var empty = await PythonHarness.RunAsync(
            "src/checker/properties.py", "examples/aws1/agent-policy.dw",
            "--property", "examples/aws1/EmptyTrajectory.tla");

        Assert.True(empty.ExitCode == 1, empty.Output);
        Assert.Contains("BROKEN", empty.Output);
        Assert.Contains("AgentCore's event schema", empty.Output);

        // And on the corrected set, the same claim holds.
        var fixedSet = await PythonHarness.RunAsync(
            "src/checker/properties.py", "examples/aws1/fixed/agent-policy.dw",
            "--property", "examples/aws1/fixed/EmptyTrajectory.tla");

        Assert.True(fixedSet.ExitCode == 0, fixedSet.Output);
        Assert.Contains("every claim holds", fixedSet.Output);

        // Policy 7, against the sentence the article prints beside it. `unless` blocks the rule
        // when its body holds, so this permits writes only while the advisor is ABSENT.
        var decay = await PythonHarness.RunAsync(
            "src/checker/properties.py", "examples/aws1/07-trust-decay.dw",
            "--property", "examples/aws1/TrustDecay.tla");

        Assert.True(decay.ExitCode == 1, decay.Output);
        Assert.Contains("BROKEN", decay.Output);
        // The counterexample must be visible: a violation nobody can see is not evidence.
        Assert.Matches(@"gap = \d+", decay.Output);

        // The two trade protections are alternatives, not requirements.
        var gate = await PythonHarness.RunAsync(
            "src/checker/properties.py", "examples/aws1/agent-policy.dw",
            "--property", "examples/aws1/TradeGate.tla");

        Assert.True(gate.ExitCode == 1, gate.Output);
        Assert.Contains("BROKEN", gate.Output);
        Assert.Contains("prereq = ", gate.Output);

        // A fragment alone is VACUOUS, and the blame names the gate that never opens rather than
        // leaving the reader to work it out.
        var alone = await PythonHarness.RunAsync(
            "src/checker/properties.py", "examples/aws1/03-data-freshness.dw");

        Assert.True(alone.ExitCode == 0, alone.Output);
        Assert.Contains("VACUOUS", alone.Output);
        Assert.Contains("because: formerly within 30s get_market_price::response{ eventResource: resource }",
                        alone.Output);
    }

    /// <summary>
    /// A property module states what a policy is <i>supposed</i> to mean, and catches an edit the
    /// three built-in checks describe wrongly.
    /// </summary>
    /// <remarks>
    /// <para>
    /// VACUOUS, REDUNDANT/DEAD and diff are the claims statable <b>without knowing intent</b>. A
    /// property is the other kind: only the author can write it. Both extend the same generated
    /// <c>PolicyUnderTest.tla</c> — <c>Vacuity.tla</c> is itself just a property module we ship.
    /// </para>
    /// <para>
    /// <c>firewall_open.dw</c> is the point. Dropping the <c>forbid</c> and widening a permit lets
    /// the whole internet connect on port 22, and the built-in checks do <i>not</i> miss it
    /// silently — they report <b>REDUNDANT permit #1</b>, which is true, and whose advice (delete
    /// the redundant rule) shrinks the policy and leaves the hole. The redundancy is a symptom;
    /// a check that cannot know what the policy was for cannot say which of the two rules is the
    /// mistake. The property can, and names the request: port 22 from an external origin.
    /// </para>
    /// <para>
    /// Both halves are asserted. That the property holds on the good policy is worth little on its
    /// own — a claim that ranges over nothing also holds. It is the pair that means something.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task APropertyStatesWhatThePolicyIsSupposedToMean()
    {
        var good = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall.dw",
            "--property", "tests/policies/firewall.tla");

        Assert.True(good.ExitCode == 0, good.Output);
        Assert.Contains("every claim holds", good.Output);

        // The careless edit: the claim breaks, and the counterexample names the request.
        var open_ = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall_open.dw",
            "--property", "tests/policies/firewall.tla");

        Assert.Equal(1, open_.ExitCode);
        Assert.Contains("OutsideIsRefused", open_.Output);
        Assert.Contains("external", open_.Output);

        // And the built-in checks on that same policy point at the WRONG rule — which is why the
        // fourth kind of check exists rather than being a nicety.
        var builtin = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall_open.dw");

        Assert.True(builtin.ExitCode == 0 || builtin.ExitCode == 1, builtin.Output);
        Assert.Contains("REDUNDANT permit #1", builtin.Output);
    }

    /// <summary>
    /// Permissiveness: did this edit <b>add</b> permissions, <b>remove</b> them, both, or
    /// neither? The question a policy author actually has when editing a set somebody else
    /// wrote — and "did they differ" is the weaker version of it that nobody can act on.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Same mechanism as the load-bearing check — compare two policy sets at every decision
    /// across every session — differing only in where the second set comes from. That is why
    /// there is no separate spec: a duplicated session model would drift, and this repo already
    /// carries <c>src/translator/dw_to_tla.py --check</c> because copies drift. The direction
    /// comes from splitting one <c>mattered</c> flag into <c>widened</c> and <c>narrowed</c>,
    /// each recorded only at a session's FIRST divergence — past that point the exploration is
    /// walking a history the other set would never have produced, so a later disagreement is not
    /// evidence about it.
    /// </para>
    /// <para>
    /// The vocabulary is Cedar Analysis's — Equivalent / More Permissive / Less Permissive /
    /// Incomparable — because agreeing with the neighbouring tool costs nothing. What differs is
    /// the domain: Cedar compares a policy as a function of one <i>request</i>, and this compares
    /// over <i>sessions</i>, which is the only way a rate limit or an approval window is visible
    /// at all.
    /// </para>
    /// <para>
    /// <b>EQUIVALENT is the answer that must never be wrong</b>, because it tells someone their
    /// edit was safe. It rests on the action vocabulary being the <b>union</b> of both files:
    /// take it from the first alone and an action only the second mentions is never attempted,
    /// so the run reports no difference having never looked. The last case below pins exactly
    /// that, and dropping the union turns it red.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task PolicyComparisonReportsWhichDirectionAnEditMoved()
    {
        // One line apart: approvals permitted, versus forbidden. The first allows strictly more.
        var wider = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/docs_trading.dw",
            "--against", "tests/policies/docs_trading_forbidden.dw");

        Assert.True(wider.ExitCode == 0, wider.Output);
        Assert.Contains("MORE PERMISSIVE", wider.Output);
        Assert.Contains("ApproveSale", wider.Output);

        // THE SAME PAIR, SWAPPED. Antisymmetry is the cheapest real check available on a
        // directional verdict: a bug that reported one direction regardless of argument order
        // would pass every assertion above and fail here. The witness must survive the swap too,
        // because it is the same session being described from the other side.
        var narrower = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/docs_trading_forbidden.dw",
            "--against", "tests/policies/docs_trading.dw");

        Assert.True(narrower.ExitCode == 0, narrower.Output);
        Assert.Contains("LESS PERMISSIVE", narrower.Output);
        Assert.Contains("ApproveSale", narrower.Output);
        Assert.DoesNotContain("MORE PERMISSIVE", narrower.Output);

        // Deleting the rule the checker called REDUNDANT. The two findings check each other:
        // "removing this changes no verdict" and "these files decide identically" are the same
        // claim from opposite ends, so a disagreement would mean one of them is wrong.
        var same = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/redundant_permit.dw",
            "--against", "tests/policies/redundant_permit_minimal.dw");

        Assert.True(same.ExitCode == 0, same.Output);
        Assert.Contains("EQUIVALENT", same.Output);
        Assert.DoesNotContain("PERMISSIVE", same.Output);

        // The difference is on an action only the SECOND file mentions, so this passes only if
        // the vocabulary spans both.
        var added = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/redundant_permit_minimal.dw",
            "--against", "tests/policies/added_action.dw");

        Assert.True(added.ExitCode == 0, added.Output);
        Assert.Contains("LESS PERMISSIVE", added.Output);
        Assert.Contains("Refund", added.Output);

        // THE ONLY CASE THAT COVERS THE ~Diverged GUARD, and it exists because nothing else did:
        // removing the guard leaves every assertion above green. Here a session widens at the
        // first attempt (Trade, newly permitted) and then appears to narrow at the second, on a
        // history only the NEW policy can produce — the old one denied the trade, so the forbid
        // that fires here never arms there. Counting the second observation reports INCOMPARABLE
        // on the strength of a trajectory the old policy cannot reach.
        var firstDivergenceOnly = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/edit_diverges_both_ways.dw",
            "--against", "tests/policies/edit_diverges_both_ways_old.dw");

        Assert.True(firstDivergenceOnly.ExitCode == 0, firstDivergenceOnly.Output);
        Assert.Contains("MORE PERMISSIVE", firstDivergenceOnly.Output);
        Assert.DoesNotContain("INCOMPARABLE", firstDivergenceOnly.Output);
    }

    /// <summary>
    /// The witness is told as a SESSION — the calls made, the values passed, and which were
    /// allowed — rather than as a list of action names.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>witness: Connect</c> is true and nearly useless: it names the action and drops the
    /// values, so it cannot say whether the connection that got through came from inside the
    /// network or outside it. That distinction is the entire content of a firewall policy.
    /// </para>
    /// <para>
    /// <b>Addresses are the case worth pinning.</b> TLC works in Java ints and stops at
    /// 2147483647, so an IPv4 address cannot be held as a 32-bit number and is modelled as four
    /// octets. Rendering that back as <c>[10, 0, 0, 0]</c> would be accurate and unreadable; the
    /// narrative prints <c>10.0.0.0</c>.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task TheWitnessIsToldAsASessionWithItsValues()
    {
        var run = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/firewall_ip.dw");

        Assert.True(run.ExitCode == 0, run.Output);

        // Dotted quad, not a list of octets and not a 32-bit integer.
        Assert.Matches(@"Connect\(src = \d+\.\d+\.\d+\.\d+\)", run.Output);
        Assert.DoesNotContain("src = [", run.Output);

        // The outcome of each attempt, which is what makes it a story rather than a list. The
        // forbid is live because it DENIES, the permit because it ALLOWS — so both words appear,
        // and a rendering that hardcoded either would fail here.
        Assert.Contains("denied", run.Output);
        Assert.Contains("allowed", run.Output);
    }

    /// <summary>
    /// The same verdict as <see cref="PolicyComparisonReportsWhichDirectionAnEditMoved"/>, but as
    /// JSON carrying the witness as structured EVENTS — for a reader that has to act on the answer
    /// rather than read it.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <b>The prose summary loses exactly what a repair loop needs.</b> "ApproveSale" names the
    /// action and drops the values, so it cannot say which input reached the decision — and an
    /// agent asked to fix the policy has to know whether the session that slipped through carried
    /// port 22 or port 3389. This asserts the values survive.
    /// </para>
    /// <para>
    /// Also asserts stdout is JSON and <i>only</i> JSON. The prose reading is printed before the
    /// verdict on the normal path, and leaving it in front of the document would make every
    /// caller strip a preamble before parsing — the same class of bug as a stray
    /// <c>Console.WriteLine</c> in the stdio transport.
    /// </para>
    /// </remarks>
    [PythonHarness("properties.py")]
    public async Task PolicyComparisonEmitsTheWitnessAsStructuredEvents()
    {
        var run = await PythonHarness.RunAsync(
            "src/checker/properties.py", "tests/policies/docs_trading.dw",
            "--against", "tests/policies/docs_trading_forbidden.dw", "--json");

        Assert.True(run.ExitCode == 0, run.Output);

        // Parses as a whole document, so nothing precedes or follows it.
        using var doc = System.Text.Json.JsonDocument.Parse(run.Output);
        var root = doc.RootElement;

        Assert.Equal("MORE PERMISSIVE", root.GetProperty("verdict").GetString());
        Assert.True(root.GetProperty("bound").GetProperty("exhaustive").GetBoolean());

        // The direction that found nothing is null rather than absent or an empty object: a caller
        // must be able to tell "no permissions removed" from "this field was not computed".
        Assert.Equal(System.Text.Json.JsonValueKind.Null, root.GetProperty("removed").ValueKind);

        var session = root.GetProperty("added").GetProperty("session");
        Assert.True(session.GetArrayLength() >= 1, run.Output);

        var first = session[0];
        Assert.Equal("ApproveSale", first.GetProperty("action").GetString());
        Assert.Equal("request", first.GetProperty("kind").GetString());

        // THE POINT OF THE WHOLE THING: the input VALUES, which the prose form discards. `stock`
        // is the field docs_trading.dw joins on, and it arrives as a plain number rather than as
        // the tagged {k,v} record the model uses internally.
        Assert.Equal(System.Text.Json.JsonValueKind.Number,
            first.GetProperty("input").GetProperty("stock").ValueKind);
    }

    /// <summary>
    /// A counterexample, carried back into Dogwood's own language and put to the real engine.
    /// </summary>
    /// <remarks>
    /// <para>
    /// A broken claim ends in a TLA+ state — <c>gap = 960</c> — in units nobody wrote down,
    /// belonging to a module a tool may have drafted. The input to all of this was a <c>.dw</c>
    /// file its author can read; an answer they cannot check is an answer they will not act on.
    /// So the module's own recipe for a session is evaluated at that value, rendered as a Dogwood
    /// <c>.log</c> trace, and handed to <c>dogwood replay</c>.
    /// </para>
    /// <para>
    /// <b>The replay is a different KIND of evidence from everything else in this suite.</b> Every
    /// other verdict rests on our TLA+ semantics being a faithful reading of Dogwood — established
    /// by differential testing, which is a very good argument rather than a proof. A replay is the
    /// reference implementation answering directly, so a confirmed finding no longer depends on us
    /// being right about the language.
    /// </para>
    /// <para>
    /// The half with no symptom is the DIRECTION: whether a claim demanded an allow or a refusal.
    /// Invert it and a correct policy is reported as broken, with engine output apparently proving
    /// it. The harness asserts both polarities on two claims that differ only in which way round
    /// they read, and asserts that a state which does <i>not</i> break the claim yields no verdict
    /// at all rather than a guess.
    /// </para>
    /// <para>
    /// <b>And the evidence has to be runnable, not merely printed.</b> The kept directory carries a
    /// copy of the policy, a generated Cedar schema, the trace and a README with the exact command —
    /// so it can be moved, attached to a ticket, or handed to somebody without this checkout and
    /// still answer for itself. The harness <i>executes</i> that command and compares its output to
    /// the verdict the finding claims: a README that tells somebody to run something other than what
    /// produced the answer is worse than no README, because they run it, get something different,
    /// and the disagreement is ours.
    /// </para>
    /// <para>
    /// The engine half needs the built binary and skips without it; the reading half — where the
    /// reasoning lives — runs either way.
    /// </para>
    /// </remarks>
    [PythonHarness("witness_replay.py", "strands")]
    public async Task ACounterexampleIsCarriedBackIntoDogwood()
    {
        var run = await PythonHarness.RunAsync("tests/strands/witness_replay.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("a claim that the policy must REFUSE is read as demanding a refusal", run.Output);
        Assert.Contains("a claim that the policy must ALLOW is read as demanding an allow", run.Output);
        Assert.Contains("a state that does NOT break the claim yields no demand, not a guess", run.Output);
        Assert.Contains("a value with no Dogwood form is refused, not guessed", run.Output);
        Assert.Contains("the event schema reaches the engine when there is one", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    #endregion
}
