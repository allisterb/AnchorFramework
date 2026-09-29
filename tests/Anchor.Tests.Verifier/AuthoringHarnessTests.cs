namespace Anchor.Tests.TLAPlus;

/// <summary>
/// What the agent WRITES, and the gates on each of them: a drafted property module, the plain-
/// English statement of what it forbids, a clarifying question about an ambiguous request, and an
/// unattended report over a whole directory. Every one of these can be produced fluently and be
/// worthless, so every one of them is gated here.
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
/// This class held 87s of the 508s when the split was measured. It has since gained
/// <c>APersonRefinesTheRequirementUntilTheGatesPass</c>, whose harness takes <b>103s</b> run on its
/// own — so this class is now the suite's floor, and <c>dotnet test --filter</c> over it alone
/// measures <b>5m57s</b>. The two figures do not reconcile, which means the 87s above predates
/// something and should be re-measured before the split is rebalanced rather than trusted.
/// </para>
/// <para>
/// The new test was 169s as first written. The three passes it dropped were re-observations of
/// facts asserted next door; what remains are mutation-scoring runs a scenario actually turns on.
/// </para>
///
/// See <see cref="PythonHarnessAttribute"/> for why any of these may report as skipped.
/// </remarks>
public class AuthoringHarnessTests : TestsRuntime
{
    #region Methods

    /// <summary>
    /// Drafting a property module, and the gate that makes it safe: a draft is kept only if it
    /// <b>could have failed</b>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Drafting is a convenience; refusing to keep one that says nothing is the feature. The
    /// most-reported pathology in agentic verification is a model asked to produce both an artifact
    /// and its specification discovering that a trivial specification is the cheapest way to pass —
    /// and the failure mode is a property that is perfectly, uselessly <i>true</i>. Mutation is the
    /// only mechanical defence: break the policy and see whether the property notices.
    /// </para>
    /// <para>
    /// The negative case is the one that matters, and it is asserted three ways — the draft is
    /// rejected, it is rejected <i>for ranging over nothing that could break it</i>, and nothing is
    /// written to disk. A rejected draft must also not clobber a module somebody wrote by hand,
    /// which is the realistic way this feature would do damage.
    /// </para>
    /// <para>
    /// <b>There are two gates, and the harness carries a fixture each one lets through.</b> Reading
    /// the module catches a claim nothing it ranges over can break, in milliseconds. Mutation
    /// catches a tautology about the <i>decision</i> — <c>Grants(r) \/ ~Grants(r)</c> — which
    /// reading cannot see, because the explainer deliberately does not evaluate the authorization
    /// semantics. A change that collapsed the two into one would pass one fixture and fail the
    /// other, which is the point of keeping both.
    /// </para>
    /// </remarks>
    [PythonHarness("property_authoring.py", "strands")]
    public async Task ADraftedPropertyIsKeptOnlyIfItCouldHaveFailed()
    {
        var run = await PythonHarness.RunAsync("tests/strands/property_authoring.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("a true-but-empty property is rejected", run.Output);
        Assert.Contains("it was rejected for ranging over nothing that could break it", run.Output);
        Assert.Contains("and NOTHING was written", run.Output);
        Assert.Contains("a tautology about the decision is rejected by MUTATION", run.Output);
        Assert.Contains("and the existing module is restored, not clobbered", run.Output);

        // A module that will not COMPILE, and one that compiles and then dies while evaluating,
        // are both "no verdict" rather than a broken policy. The second survived the first fix
        // because SANY resolves names and not record fields.
        Assert.Contains("...and the checker says NO VERDICT rather than BROKEN", run.Output);
        Assert.Contains("...and gets NO VERDICT rather than BROKEN", run.Output);

        // THE DECISION PROBE. Between the static gate and the mutation gate: does the policy's
        // answer VARY over the states this property names? Five drafted properties out of five
        // failed exactly this way on one real policy set, and only mutation scoring caught them —
        // a TLC run per mutant, to report the symptom rather than the cause.
        Assert.Contains("a property whose policy answers differently VARIES", run.Output);
        Assert.Contains("a policy that refuses everything the property names is CONSTANT", run.Output);
        Assert.Contains("...and the diagnosis names the decision term and the likely cause", run.Output);
        // A gate that cannot read a module must not reject it.
        Assert.Contains("a module with no decision term is SKIPPED, not rejected", run.Output);

        // The evaluator, on the shape that silently broke it: a cross-kind join plus an aggregate.
        Assert.Contains("...and returns the right values either side of the window", run.Output);

        Assert.DoesNotContain("FAIL", run.Output);
    }

    /// <summary>
    /// The unattended directory audit — <c>anchor check &lt;directory&gt;</c>: every policy found
    /// by globbing, every <c>.tla</c> paired with the policy its header names, and a directory with
    /// <b>no</b> stated intentions told plainly that its clean report means much less.
    ///
    /// It was the <c>auto</c> verb, and that name claimed the wrong thing: "auto" means
    /// autoformalization in this field, and nothing here formalizes anything — every intentional
    /// claim it checks is a <c>.tla</c> module a person wrote by hand. What was automated was the
    /// running, never the specifying.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The orchestration is what is pinned here, not the checks — those have their own tests. What
    /// would rot silently is the honesty: <c>auto</c> over policies with no <c>.tla</c> beside them
    /// produces a report that looks exactly like a pass, and the only thing between that and a
    /// false sense of security is a paragraph saying which questions were never asked.
    /// </para>
    /// <para>
    /// Also pinned: the headline must not be a vacuous truth. With zero stated intentions, "every
    /// stated intention holds" is true and says nothing — which is the precise failure this whole
    /// project exists to catch, and would be an embarrassing one to ship in its own report.
    /// </para>
    /// </remarks>
    [PythonHarness("audit_directory.py", "strands")]
    public async Task TheAuditFindsEveryPolicyAndSaysWhatItDidNotCheck()
    {
        var run = await PythonHarness.RunAsync("tests/strands/audit_directory.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("a module naming no policy is reported, not dropped", run.Output);
        Assert.Contains("BUT the report says no intentions were stated", run.Output);
        Assert.Contains("and does not claim every intention holds", run.Output);
        Assert.Contains("a broken intention is listed first", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    /// <summary>
    /// The audit's LLM is optional unless asked for by name. Unreachable and unnamed, it is a
    /// warning and the questions are skipped; named with --llm, --provider or --config, it stops the
    /// run before any TLC, or exits 3 after the report when it fails only at the first question.
    /// </summary>
    /// <remarks>
    /// Calls no model: the harness empties every credential from its environment and replaces
    /// <c>review</c> and <c>build_model</c> with stand-ins that raise.
    /// </remarks>
    [PythonHarness("audit_llm_preflight.py", "strands")]
    public async Task TheAuditsLlmIsAWarningUnlessAskedForByName()
    {
        var run = await PythonHarness.RunAsync("tests/strands/audit_llm_preflight.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("readiness never holds the key itself", run.Output);
        Assert.Contains("...before the first TLC run", run.Output);
        Assert.Contains("a SystemExit from the LLM no longer loses the report", run.Output);
        Assert.Contains("with --llm, a question that fails after a good probe writes the report and exits 3", run.Output);
        Assert.Contains("--llm with a model the probe cannot reach stops the run, exit 3", run.Output);
        Assert.Contains("without --llm, --provider or --config nothing is spent on a probe", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    /// <summary>
    /// Ambiguity reporting: a request that admits more than one policy is raised <b>only when the
    /// readings actually decide something differently</b>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// A verifier answers questions about a policy that exists; it cannot say the <i>request</i>
    /// was ambiguous, because by then a reading has already been chosen — silently, by whatever
    /// wrote the policy. That gap is what this closes, and the competing readings are compared
    /// against each other rather than merely listed.
    /// </para>
    /// <para>
    /// <b>The negative case is the one that keeps it honest.</b> A model can always manufacture a
    /// distinction, and an assistant that asks a clarifying question every time trains people to
    /// click past it. Two readings that decide every session alike must not reach a person however
    /// different their text — and "I could not check that one" must not read as "they agree".
    /// </para>
    /// </remarks>
    [PythonHarness("clarify_readings.py", "strands")]
    public async Task AmbiguityIsVerifiedBeforeItIsRaised()
    {
        var run = await PythonHarness.RunAsync("tests/strands/clarify_readings.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("and it comes with a session, not just a verdict", run.Output);
        Assert.Contains("readings that agree on every session are NOT material", run.Output);
        Assert.Contains("an unusable reading is excluded from a no-difference claim", run.Output);
        Assert.Contains("no readings is not the same as no ambiguity", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);
    }

    /// <summary>
    /// The plain-English explainer: what a property module <b>forbids</b>, said before anything is
    /// checked.
    /// </summary>
    /// <remarks>
    /// <para>
    /// This is the checkpoint at the one boundary where the literature says autonomy fails — the
    /// formulation of the property itself. Everything downstream of a property is mechanical and
    /// checkable; everything upstream is a person saying what they meant. A property that says
    /// something <i>other</i> than what its author meant is checked just as rigorously, and passes
    /// just as convincingly.
    /// </para>
    /// <para>
    /// <b>Nothing here runs TLC</b>, which is the feature rather than a shortcut: a checkpoint that
    /// costs minutes is a checkpoint people skip. What would rot silently is the <i>sense</i> of the
    /// generated English — <c>~Grants(req)</c> glossed as "the policy GRANTS it" reads perfectly and
    /// is exactly backwards — so the harness asserts the direction of the rendering per shape, in
    /// both polarities, rather than the shape of the output.
    /// </para>
    /// <para>
    /// The counting is the other half. <c>A =&gt; B</c> tests nothing in any state where <c>A</c> is
    /// false, so "applies to 3 of the 6" is the size of the experiment, and <i>none of them</i> is a
    /// claim that will pass having examined nothing.
    /// </para>
    /// </remarks>
    [PythonHarness("property_explainer.py", "strands")]
    public async Task WhatAPropertyForbidsIsStatedBeforeItIsChecked()
    {
        var run = await PythonHarness.RunAsync("tests/strands/property_explainer.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("a claim that the policy must ALLOW forbids a refusal", run.Output);
        Assert.Contains("a claim whose condition no state satisfies is reported as vacuous", run.Output);
        Assert.Contains("a tautology about the DECISION is not caught by reading alone", run.Output);
        Assert.Contains("the policy's decision is UNKNOWN, never guessed", run.Output);

        // THE BULLETED CONJUNCTION LIST — how Lamport writes one, and what a drafter reaches for.
        // This reader is infix, so a leading <c>/\</c> had no left operand: the parse failed, the
        // Init was reported unread, and <c>total</c> was 0. Because <c>Claim.vacuous</c> requires
        // <c>total &gt; 0</c>, the static vacuity gate was silently INACTIVE for every module
        // written that way — failing open, which is the right direction, but not doing its job and
        // saying nothing about it.
        Assert.Contains("a bulleted /\\ list is read the same as the inline form", run.Output);
        Assert.Contains("...so a vacuous claim under a bulleted Init is now caught", run.Output);

        // And when an Init genuinely cannot be read, the rendering must say so rather than assert a
        // count. It said "applies to NONE of the 0 states" — on all six claims of a property TLC
        // had just checked and found to hold over 48 states, in front of a person at the hitl
        // checkpoint being asked to confirm it. A nested list stays unread on purpose: misreading
        // an indentation-scoped list would be worse than declining to read it.
        Assert.Contains("ok    ...and the rendering does NOT say it applies to none of them", run.Output);
        Assert.Contains("ok    ...but says plainly that the states were never counted", run.Output);

        Assert.DoesNotContain("FAIL", run.Output);
    }

    /// <summary>
    /// The authoring pipeline as the Strands <c>Graph</c> that runs it: one agent drafts, a
    /// different one reports, and the two gates between them are criteria in code.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The load-bearing assertion is the last one. <c>tests/strands/anchor_workflow.py</c> chose
    /// this shape by checking four properties against four wirings — but it chose it over graphs
    /// built from scripted stand-ins. This runs the same translation over the graph
    /// <c>pipeline.build</c> actually returns and re-proves <c>AlwaysReports</c> on it, so the
    /// shape that was checked and the object that runs cannot drift apart.
    /// </para>
    /// </remarks>
    [PythonHarness("pipeline_run.py", "strands")]
    public async Task TheAuthoringPipelineRunsAsTheGraphThatWasChecked()
    {
        var run = await PythonHarness.RunAsync("tests/strands/pipeline_run.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("all checks passed", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);

        // A rejected draft costs nothing downstream — no TLC, no second model call — and still
        // reports. Both halves, because either alone would be the wrong behaviour.
        Assert.Contains("ran 4/8: describe, draft, preflight, report", run.Output);
        Assert.Contains("ok    the answerer was not invoked", run.Output);
        Assert.Contains("ok    report ran anyway", run.Output);
        Assert.Contains("ok    findings.md says nothing was verified", run.Output);

        // An accepted draft goes the whole way, and the answerer sees the verdicts rather than the
        // drafter's module — the separation as it actually lands, not as it was intended.
        Assert.Contains("ran 8/8: describe, draft, preflight, score, review, check, answer, report", run.Output);
        Assert.Contains("ok    the answerer did NOT see the draft", run.Output);

        // And the claim the whole graph exercise was for.
        Assert.Contains("ok    AlwaysReports HOLDS on the graph that actually runs", run.Output);

        // THE ROUND TRIP — the only gate that compares the property against the BRIEF rather than
        // against the policy, and the only one with no oracle behind it. It may reject; its
        // agreement is an agreement between two models. The last two assertions are the ones that
        // keep it honest, and if either ever has to change because the wording got stronger, that
        // is precisely the defect they exist to catch.
        Assert.Contains("ok    a mismatch stops the run at review", run.Output);
        Assert.Contains("ok    findings.md carries the reviewer's reasoning", run.Output);
        Assert.Contains("ok    an agreement is reported as an agreement, not a proof", run.Output);
        Assert.Contains("ok    ...and says the reviewer never saw the formal claim", run.Output);
        // Fail-OPEN on a non-answer, uniquely here: acceptance proves nothing anyway, so blocking
        // would give this gate an authority the others have and it does not.
        Assert.Contains("ok    an unparseable review does not stop the run", run.Output);

        // The retry, which exists because a live run lost a semantically perfect module to one
        // stray `*`. A round that is not told WHERE cannot fix it, so the location is pinned too.
        Assert.Contains("ok    it took a second round", run.Output);
        Assert.Contains("ok    ...and where SANY choked", run.Output);

        // AND THE ROUND IS NOT PAID FOR TWICE. One Agent drafts every round, so its conversation
        // already holds round 1 — prompt, 15 KB of manual, 8 KB of vocabulary and all. Building a
        // later round from `draft_prompt` sent a second copy on top of that history. Found in a
        // live run's own cost table, and the arithmetic was exact: round 1 was 6,399 in / 6,580
        // out, and round 2's input was 19,501 = 12,979 + 6,522, that last figure being
        // `draft_prompt` charged again for text already in front of the model.
        Assert.Contains("ok    ...and the manual was not sent a second time", run.Output);
        Assert.Contains("ok    ...nor the vocabulary", run.Output);

        // AND THAT IT IS NOT A CYCLE. A retry edge in the graph would put this shape outside what
        // either model can express — `oracle` is fixed per behaviour, so a retry edge cannot say
        // "again, then stop", and StartBatch increments `runs` with no guard. If `draft` ever runs
        // twice, everything proved about this graph stops applying to it.
        Assert.Contains("ok    the graph stayed acyclic: draft ran once", run.Output);

        // Running out of rounds ends in a report, not a stopped run.
        Assert.Contains("ok    the run was NOT aborted", run.Output);
        Assert.Contains("ok    findings.md says the allowance ran out", run.Output);

        // The bound travels with the verdict. A live run reported "for all possible requests and
        // scenarios" over a property ranging across three ports and two origins.
        Assert.Contains("ok    the answerer was told what the property RANGES OVER", run.Output);

        // Budget caps. A trip is a stop_reason and the agent returns normally, so Graph marks the
        // node COMPLETED — a capped agent is indistinguishable from a finished one unless someone
        // looks. Both halves are pinned: a cut-off draft must not reach the gates as a draft, and
        // a cut-off report must say so of itself, since a truncated report reads as a whole one.
        Assert.Contains("ok    a cut-off draft is a failed round, not a draft", run.Output);
        Assert.Contains("ok    findings.md leads with the cap", run.Output);
        Assert.Contains("ok    the report says of ITSELF that it is incomplete", run.Output);

        // What the run cost. The accounting one matters most: metrics.accumulated_usage is
        // cumulative across invocations of the same Agent, and the drafter is reused every round,
        // so reading it per call would bill round 1 again on round 2 — 15, then 30, for two calls
        // that each cost 15. Silent, and it grows with the round count.
        // NOTHING ABORTS. A node that raises ends the run with no findings.md at all — the hole
        // AlwaysReports cannot cover, since it is stated over phase = "DONE" and the property
        // cannot be strengthened (the model lets any node fail). Discharged in code instead, and
        // this is where that is held to.
        Assert.Contains("ok    an unreadable policy is a rejection, not an abort", run.Output);
        Assert.Contains("ok    a stage that throws does not abort the run", run.Output);
        Assert.Contains("ok    findings.md says it was ANCHOR that failed, not the policy", run.Output);
        Assert.Contains("ok    all four gates declared as exclusive decisions", run.Output);

        Assert.Contains("ok    findings.md reports the cost", run.Output);
        Assert.Contains("ok    ...each at ITS OWN cost, not the agent's running total", run.Output);
        Assert.Contains("ok    and a per-stage time for every stage that ran", run.Output);

        // A directory sweep. The discrimination is the point — the SAME drafted property must hold
        // on the sound policy and break on the unsound one, or the sweep is only proving it can
        // finish. And a policy with no stated intent is named rather than quietly skipped.
        Assert.Contains("ok    the correct policy passes", run.Output);
        Assert.Contains("ok    and the broken one is caught", run.Output);
        Assert.Contains("ok    the summary names the policy with no stated intent", run.Output);
        // Progress as it lands. A sweep is minutes per policy and used to print nothing until it
        // was over — the same defect the report exists to avoid, in the terminal instead.
        Assert.Contains("ok    each policy is announced BEFORE it runs and reported after", run.Output);
    }

    /// <summary>
    /// <c>hitl</c>: the same pipeline with a <b>person</b> as one of the gates, at the one boundary
    /// in autoformalisation that has no oracle behind it.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Everything downstream of a property module is mechanical — does it compile, does the
    /// decision vary, does it catch a mutant, does it hold — and every one of those is a criterion
    /// in code that cannot be talked out of its answer. Everything <i>upstream</i> is a person
    /// saying what they meant, and nothing here can check a property against an intention nobody
    /// wrote down. A live sweep accepted one requirement in five, and the four that failed failed
    /// on the <i>semantic</i> gate: well-formed statements of something the brief did not quite
    /// say.
    /// </para>
    /// <para>
    /// <b>The load-bearing assertion is that the person is never shown TLA+.</b> The gates talk to
    /// the drafter, and their complaints are right for it — "the .cfg names INVARIANT X, which the
    /// module does not define" is the sentence that gets the next round fixed. Forwarded to
    /// somebody who was asked for a requirement in English, it is a demand that they debug a file
    /// they have never seen, and that is precisely what the first run of the harness caught. The
    /// scan runs over what actually reached the scripted person, including the reading of the
    /// claim at the checkpoint, rather than over the code that produced it.
    /// </para>
    /// <para>
    /// The other one is the footer. Being in this mode is not a confirmation: a session whose
    /// allowance ran out asked four questions and kept no property, and crediting the person there
    /// would claim the strongest thing in the document on the strength of the mode it was run in.
    /// </para>
    /// <para>
    /// <c>hitl</c> adds one node to the graph, so <c>AlwaysReports</c> is <i>re-proved</i> over the
    /// graph <c>build_hitl</c> returns rather than inherited from the <c>auto</c> graph it is no
    /// longer identical to — and <c>auto</c> is asserted unchanged in the same breath.
    /// </para>
    /// </remarks>
    [PythonHarness("hitl_loop.py", "strands")]
    public async Task APersonRefinesTheRequirementUntilTheGatesPass()
    {
        var run = await PythonHarness.RunAsync("tests/strands/hitl_loop.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("all checks passed", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);

        // The shape. One more gate, still exclusive, still reports on every path — and the auto
        // graph untouched, because four properties were chosen against that exact shape.
        Assert.Contains("ok    the person's checkpoint is a fifth exclusive decision", run.Output);
        Assert.Contains("ok    AlwaysReports HOLDS on the hitl graph that actually runs", run.Output);
        Assert.Contains("ok    ...and the auto graph still has exactly four", run.Output);
        Assert.Contains("ok    no confirm node in the auto graph", run.Output);

        // WHAT REACHES THE PERSON. The whole premise of the mode is that they refine a requirement
        // they can read; two of these tokens were leaking on the first run, straight out of a gate
        // complaint written for the drafter.
        Assert.Contains("ok    nothing shown to the person when a gate rejects the draft mentions `INVARIANT`", run.Output);
        Assert.Contains("ok    nothing shown to the person when a gate rejects the draft mentions `.cfg`", run.Output);
        Assert.Contains("ok    nothing shown to the person at the checkpoint mentions `|->`", run.Output);
        Assert.Contains("ok    every line of the reading reached the person", run.Output);

        // WHICH QUESTION, AND WHY THAT ONE. Asking about the wrong gate costs a whole attempt, and
        // the ordering is the diagnosis: a policy that refuses everything the property names also
        // fails mutation scoring, and only one of the two has an answer a person can give.
        Assert.Contains("ok    a claim that cannot fail asks which VALUES to check at", run.Output);
        Assert.Contains("ok    a property that catches no mutant asks what must NEVER be allowed", run.Output);
        Assert.Contains("ok    a policy that refuses everything asks what must have happened FIRST", run.Output);
        Assert.Contains("ok    ...even though the mutation gate is what rejected it", run.Output);
        Assert.Contains("ok    ...and tells them they may overrule the reviewing model", run.Output);

        // What no clarification can fix is not put to a person, and the loop stops rather than
        // spending a model call per attempt asking them to rephrase their way out of a 404.
        Assert.Contains("ok    an unreachable model is not a question for the person", run.Output);
        Assert.Contains("ok    an unreadable policy ends the session after ONE attempt", run.Output);
        Assert.Contains("ok    ...without asking the person anything", run.Output);

        // The answers become part of the requirement — appended, never substituted, because the
        // original text is what the reviewing gate compares against and what an auditor reads.
        Assert.Contains("ok    the ORIGINAL brief survives verbatim", run.Output);
        Assert.Contains("ok    ...with the answer appended, not substituted", run.Output);
        Assert.Contains("ok    and the DRAFTER saw it on the next attempt", run.Output);

        // THE CHECKPOINT, and the scenario it exists for: every gate passed, a second model
        // agreed, and the property is about the wrong rule. Nothing else can catch that.
        Assert.Contains("ok    the person was shown what the claim forbids", run.Output);
        Assert.Contains("ok    the person's `no` stops the run", run.Output);
        Assert.Contains("ok    findings.md says the gate was the PERSON'S, not a criterion in code", run.Output);

        // EVERY STAGE ANNOUNCES ITSELF. Found by running the mode for real: on a six-field policy
        // the wait between the command and the first question is minutes of model calls and TLC
        // runs, and it printed nothing at all — indistinguishable from a hang. `auto` reports each
        // policy as it lands for exactly this reason; the interactive mode, where somebody is
        // actually sitting there waiting, did not.
        Assert.Contains("ok    `draft` says it has started", run.Output);
        Assert.Contains("ok    `score` says it has started", run.Output);
        Assert.Contains("ok    ...and says how long it took", run.Output);

        // Every exit reports, and a person who leaves is not kept in a loop. Saying no at the
        // checkpoint and then declining to explain leaves the brief unchanged — so a further
        // attempt would re-draft from the same text and show them the identical reading, once per
        // attempt remaining.
        Assert.Contains("ok    saying no and then nothing also ends the session", run.Output);
        Assert.Contains("ok    ...rather than asking the same thing again", run.Output);

        // And what the documents are allowed to claim. If either of these has to change because
        // the wording got stronger, that is the defect they exist to catch.
        Assert.Contains("ok    ...and says the person did NOT read the formal claim", run.Output);
        Assert.Contains("ok    ...and does not claim a person verified anything", run.Output);
        Assert.Contains("ok    ...and does not credit the person with confirming anything", run.Output);
    }

    /// <summary>
    /// The drafter's own tools — the mechanical checks it may run on itself, and the gates it
    /// deliberately cannot see.
    /// </summary>
    /// <remarks>
    /// <para>
    /// It was writing TLA+ blind: a bare <c>Agent</c> with a system prompt, one prompt in and a
    /// module out, learning what was wrong a whole graph round-trip later from feedback assembled
    /// by <c>stage_draft</c> — and sent on a conversation that had grown by the previous attempt.
    /// Three live sessions in a row died on one typing rule. It now has <c>check_module</c>,
    /// <c>what_it_forbids</c> and <c>evaluate</c>, and the harness drives the exact module those
    /// sessions died on: <c>check_module</c> reports it in one call, with the rule TLC's own
    /// message does not mention.
    /// </para>
    /// <para>
    /// <b>The boundary is what this test is really for.</b> There is no mutation scoring here and
    /// there never should be: <c>score</c> asks whether the property notices the policy breaking,
    /// and a model that can run it will tune the property until it catches a mutant — optimising
    /// against the gate rather than stating the requirement, which is the most-reported pathology
    /// in this field and the thing the whole pipeline shape exists to prevent. The reviewing model
    /// is absent for the same reason. Asserted by name <i>and</i> by inspecting every tool's actual
    /// output, because a tool that merely shelled out with <c>--mutation-score</c> would pass a
    /// name check and hand the model the gate anyway.
    /// </para>
    /// <para>
    /// Also pinned: the tools take no policy or bound argument — a drafter that picks its own
    /// <c>--max-fields</c> can widen the check until something passes — and a scripted model that
    /// emits no tool calls is unaffected, since every other harness drives this pipeline that way.
    /// </para>
    /// </remarks>
    [PythonHarness("drafting_tools.py", "strands")]
    public async Task TheDrafterChecksItsOwnWorkButCannotSeeTheGates()
    {
        var run = await PythonHarness.RunAsync("tests/strands/drafting_tools.py");
        Assert.True(run.ExitCode == 0, run.Output);

        Assert.Contains("all checks passed", run.Output);
        Assert.DoesNotContain("FAIL", run.Output);

        // THE BOUNDARY — by name, and by what the tools actually return.
        Assert.Contains("ok    exactly the three mechanical checks, and no others", run.Output);
        Assert.Contains("ok    nothing named `mutation`", run.Output);
        Assert.Contains("ok    ...and no tool's ANSWER mentions `mutant`", run.Output);
        Assert.Contains("ok    the drafter cannot consult the reviewer", run.Output);

        // The failure that cost three live sessions, caught in one call.
        Assert.Contains("ok    it compiles, and is reported as NOT evaluating", run.Output);
        Assert.Contains("ok    ...and attaching the rule that message does not mention", run.Output);

        // A property that FAILS is an acceptable answer. A drafter told only "it does not hold"
        // weakens the claim until it does — the pathology the separation exists to prevent.
        Assert.Contains("ok    ...and it is told never to weaken a claim to make it hold", run.Output);
        Assert.Contains("ok    ...and not to weaken a claim to make it hold", run.Output);

        // It cannot choose its own terms, and it is actually told to use what it has.
        Assert.Contains("ok    `check_module` takes no policy argument", run.Output);
        Assert.Contains("ok    ...and says to call it BEFORE answering", run.Output);

        // And nothing that drives this with a scripted model has to know tools exist.
        Assert.Contains("ok    an injected drafter is used as given, tools or not", run.Output);
    }

    #endregion
}
