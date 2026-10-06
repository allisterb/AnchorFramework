"""`src/agent/drafting.py`: what the drafter may check for itself, and what it must never see.

THE DRAFTER WAS WRITING TLA+ BLIND. It was a bare `Agent` with a system prompt -- one prompt in, a
module out -- and it learned what was wrong a whole graph round-trip later, from feedback assembled
by `stage_draft` and sent on a conversation that had grown by the previous attempt. Three live
sessions in a row died on one typing rule.

  1. THE BOUNDARY, and it is the reason this file exists. `score` asks whether the property notices
     the policy breaking, and a model that can RUN that will tune the property until it catches a
     mutant -- optimising against the gate instead of stating the requirement. That is the
     documented failure mode; TLA-Prover (arXiv:2606.06133) names it for TLA+ and
     keeps its mutation gate out of the model's hands for the same reason. So: the mechanical
     checks yes, the gates that judge it no, asserted by name and
     by behaviour rather than by reading the list.
  2. THEY ANSWER, and correctly, on the real fixtures -- including the failure that cost the three
     sessions, which `check_module` reports in one call.
  3. THEY CANNOT CHOOSE THEIR OWN TERMS. The policy, the event schema and the field bound come
     from the `Run`, not from the model: a drafter that picks its own `--max-fields` can widen the
     check until something passes.
  4. A SCRIPTED MODEL STILL WORKS. Every other harness drives this pipeline with models that emit
     no tool calls at all, and tools must not become a thing those runs depend on.

    python tests/strands/drafting_tools.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_run import GOOD, agent                                   # noqa: E402

from agent import author, drafting, pipeline                           # noqa: E402

POLICIES = REPO / "tests" / "policies"
AWS2 = REPO / "examples" / "aws2"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)
        if detail:
            print(f"          {detail[:400]}")


def call(by: dict, name: str, **kw) -> str:
    """Invoke a tool the way the agent loop does."""
    return by[name]._tool_func(**kw)


def built(policy: Path, out: Path, **kw) -> tuple[pipeline.Run, dict]:
    run = pipeline.Run(policy=policy, intent="x", out=out, **kw)
    return run, {t.tool_name: t for t in drafting.tools(run)}


# -------------------------------------------------------------------------------------------
def the_boundary() -> None:
    """The gates that judge the drafter are not among the things it can call."""
    print("\nWhat the drafter may NOT reach")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-tools-") as tmp:
        run, by = built(POLICIES / "firewall.dw", Path(tmp))

        print(f"  {len(by)} tool(s): {', '.join(sorted(by))}")
        check("exactly the three mechanical checks, and no others",
              tuple(t.tool_name for t in drafting.tools(run)) == drafting.TOOL_NAMES,
              str(sorted(by)))

        # BY NAME, because a tool called `mutation_score` would be the obvious way to lose this...
        for banned in ("mutation", "score", "review", "mutant"):
            check(f"nothing named `{banned}`",
                  not any(banned in n for n in by), str(sorted(by)))

        # ...AND BY BEHAVIOUR, because the real hazard is subtler: a tool that happens to shell out
        # with --mutation-score would pass the name check and hand the model the gate anyway. Every
        # tool is driven on a real module and its whole output inspected.
        mod = (POLICIES / "firewall.tla").read_text(encoding="utf-8").replace(
            "MODULE firewall", "MODULE Intent", 1)
        cfg = (POLICIES / "firewall.cfg").read_text(encoding="utf-8")
        everything = "\n".join([
            call(by, "check_module", module=mod, config=cfg),
            call(by, "what_it_forbids", module=mod, config=cfg),
            call(by, "evaluate", expression="Num(22) = Num(22)", module=mod, config=cfg)])
        for leak in ("mutant", "caught", "MISSED", "mutation"):
            check(f"...and no tool's ANSWER mentions `{leak}`", leak not in everything.lower()
                  if leak.islower() else leak not in everything,
                  next((l for l in everything.splitlines() if leak.lower() in l.lower()), ""))

        # The reviewing model is a different agent entirely and must stay that way.
        check("the drafter cannot consult the reviewer",
              not any("review" in n or "match" in n for n in by), str(sorted(by)))


def they_answer() -> None:
    """And they are worth having: each one answers, on real modules."""
    print("\nWhat it CAN check, and the answers")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-tools-") as tmp:
        _, by = built(POLICIES / "firewall.dw", Path(tmp))
        mod = (POLICIES / "firewall.tla").read_text(encoding="utf-8").replace(
            "MODULE firewall", "MODULE Intent", 1)
        cfg = (POLICIES / "firewall.cfg").read_text(encoding="utf-8")

        said = call(by, "check_module", module=mod, config=cfg)
        print(f"    check_module: {said.splitlines()[0][:88]}")
        check("a good module comes back clean", said.startswith("Compiles, evaluates"), said[:200])
        # A PROPERTY THAT FAILS IS AN ACCEPTABLE ANSWER, said in the answer itself -- a drafter told
        # only "it does not hold" weakens the claim until it does, which is the pathology the whole
        # pipeline is built around.
        check("...and it is told never to weaken a claim to make it hold",
              "NEVER weaken" in said or "Do NOT weaken" in said, said[:300])
        # REFUSAL-ONLY IS WARNED ABOUT, NEVER REJECTED. firewall.tla has one claim each way, so it
        # gets no warning; the same module with only its refusal claim named does, and still passes.
        check("a module with claims both ways is not warned about", "WARNING" not in said, said[-300:])
        refusing = call(by, "check_module", module=mod,
                        config="SPECIFICATION Spec\nINVARIANT OutsideIsRefused\n")
        check("one whose every claim says 'must refuse' is warned, naming the claim",
              "WARNING, not a rejection" in refusing and "`OutsideIsRefused`" in refusing,
              refusing[-400:])
        check("...and is still accepted", refusing.startswith("Compiles, evaluates"), refusing[:200])

        broken = mod.replace("OutsideIsRefused ==", "OutsideIsRefused == FALSE /\\ ")
        said = call(by, "check_module", module=broken, config=cfg)
        check("a module that will not compile says so, with SANY's own words",
              said.startswith("DOES NOT COMPILE") or "Compiles, but" in said, said[:200])

        reading = call(by, "what_it_forbids", module=mod, config=cfg)
        check("the reading names each claim and what it forbids",
              "OutsideIsRefused" in reading and "forbids" in reading, reading[:200])
        check("...and counts the states it applies to",
              "applies" in reading and "of the 4" in reading, reading[:400])

        value = call(by, "evaluate", expression="Num(22) = Num(22)", module=mod, config=cfg)
        check("an expression evaluates to a value", "TRUE" in value, value[-200:])
        # MULTI-LINE, AS A MODEL WRITES IT. The wrapper used to put the expression inside a junction
        # list, where a continuation line starting left of the bullets ended the list: every
        # multi-line expression failed to parse. Five tool calls in the recorded runs died this way.
        value = call(by, "evaluate", expression="LET s == Num(22)\nIN s.v + 1", module=mod,
                     config=cfg)
        check("...and so does one written over several lines", "23" in value, value[-200:])

        # A LONG VALUE KEEPS ITS HEAD, AND SAYS IT WAS CUT. It used to arrive as its last 1500
        # characters with no notice, and the checker had already dropped every line past 60, also
        # silently. One drafter on the 2026-10-04 aws2 sweep asked for `Policies` three times.
        value = call(by, "evaluate", module=mod, config=cfg,
                     expression="[i \\in 1..200 |-> [field_with_a_long_name |-> i, other |-> i]]")
        check("a long value is shown from its start",
              "<<[field_with_a_long_name |-> 1, other |-> 1]" in value, value[:200])
        check("...and says it was truncated, and how long it was",
              "[TRUNCATED: the first 1500 of " in value, value[-300:])
        # TLC prints this one an element per line, so it is the checker's 60-line cut that applies.
        value = call(by, "evaluate", expression="[i \\in 1..3000 |-> i]", module=mod, config=cfg)
        check("a value of many lines says how many the checker did not print",
              "2940 more line(s) of the value not shown" in value, value[-300:])

    # BOTH CUTS AT ONCE, as `Policies` gets: the checker's note is past the head that is kept.
    both = drafting.clipped("y" * 2000 + "\n\n... 940 more line(s) of the value not shown; ...",
                            value=True)
    check("a value cut twice reports both cuts",
          both.startswith("y" * 1500) and "and 940 more line(s) the checker did not print" in both,
          both[-300:])
    # A FAILURE KEEPS ITS TAIL, where TLC puts the reason; anything short is untouched.
    failed = drafting.clipped("x" * 2000 + "\nThe reason.", value=False)
    check("a long failure is shown from its end, saying so",
          failed.startswith("[TRUNCATED: the last 1500") and failed.endswith("The reason."),
          failed[:120])
    check("a short answer is returned exactly", drafting.clipped("TRUE", value=True) == "TRUE")


def the_failure_that_cost_three_sessions() -> None:
    """`check_module` reports it in one call, where the pipeline took a whole round-trip."""
    print("\nThe failure three live sessions died on")
    print("-" * 78)
    # FROM tests/policies, NOT from the example directory it was produced in. The first version of
    # this read `examples/aws2/anchor/hitl-identity/attempt-2/`, and the next live run overwrote it
    # with a module that passes -- a fixture living where the tool writes is a fixture with a
    # countdown on it.
    module = POLICIES / "tagged_session.tla"
    with tempfile.TemporaryDirectory(prefix="anchor-tools-") as tmp:
        _, by = built(AWS2 / "agent-policy.dw", Path(tmp),
                      module_name="tagged_session", max_fields=6)
        said = call(by, "check_module",
                    module=module.read_text(encoding="utf-8"),
                    config=module.with_suffix(".cfg").read_text(encoding="utf-8"))

        print(f"    {said.splitlines()[0][:88]}")
        check("it compiles, and is reported as NOT evaluating",
              said.startswith("COMPILED BUT DID NOT EVALUATE"), said[:200])
        check("...quoting TLC's own message", "check equality of integer" in said, said[:600])
        # THE HINT IS THE HALF THAT MATTERS. The message names neither the variables nor the
        # tagging, so a drafter reading it alone tries arithmetic fixes -- which is what happened,
        # three times.
        check("...and attaching the rule that message does not mention",
              "must range over PLAIN values" in said, said[-400:])


def it_cannot_choose_its_own_terms() -> None:
    """The policy and the bounds come from the Run, not from the model."""
    print("\nWhat the model does not get to decide")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-tools-") as tmp:
        _, by = built(POLICIES / "firewall.dw", Path(tmp))
        for name in drafting.TOOL_NAMES:
            spec = by[name].tool_spec
            params = set((spec.get("inputSchema", {}).get("json", {})
                          .get("properties", {})).keys())
            print(f"    {name:<18} takes {sorted(params)}")
            check(f"`{name}` takes no policy argument",
                  not (params & {"policy", "policy_path", "event_schema", "max_fields"}),
                  str(sorted(params)))


def scripted_models_still_work() -> None:
    """Every other harness drives this with models that emit no tool calls at all."""
    print("\nA model that never calls a tool is unaffected")
    print("-" * 78)
    with tempfile.TemporaryDirectory(prefix="anchor-tools-") as tmp:
        run = pipeline.Run(policy=POLICIES / "firewall.dw",
                           intent="Local SSH is permitted and every external source is denied.",
                           out=Path(tmp), mutants=2)
        graph = pipeline.build(run, drafter=agent(GOOD, "draft"), answerer=agent("ok", "answer"),
                               reviewer=agent("VERDICT: MATCH", "review"))
        result = graph("go")
        ran = [n.node_id for n in result.execution_order]
        print(f"  ran {len(ran)}/{result.total_nodes}: {', '.join(ran)}")
        check("an injected drafter is used as given, tools or not",
              set(ran) == set(pipeline.STAGES), str(sorted(set(ran))))
        check("and the run is not rejected", run.rejected_at == "", run.rejected_at)


def the_prompt_says_to_use_them() -> None:
    """Tools nobody is told to call are tools nobody calls."""
    print("\nThe drafter is told to check its own work")
    print("-" * 78)
    p = author.DRAFTER_PROMPT
    for name in drafting.TOOL_NAMES:
        check(f"the prompt names `{name}`", name in p, p[-400:])
    check("...and says to call it BEFORE answering",
          "BEFORE YOU ANSWER" in p.upper(), p[-600:])
    check("...and not to weaken a claim to make it hold",
          "NEVER weaken" in p, p[-400:])
    # The reviewer's half of the threshold-edge rule: shown amounts {499, 500, 2500, 2501} for "over
    # $500", it said MATCH, and a policy whose threshold was $1000 passed every gate.
    r = pipeline.REVIEWER_PROMPT
    check("the reviewer rejects a reading that never examines the value just past a threshold",
          "JUST PAST" in r and "$501" in r, r[-500:])


def main() -> int:
    print("=" * 78)
    print("The drafter's tools, and the gates they deliberately exclude")
    print("=" * 78)

    the_boundary()
    they_answer()
    the_failure_that_cost_three_sessions()
    it_cannot_choose_its_own_terms()
    the_prompt_says_to_use_them()
    scripted_models_still_work()

    print()
    print("=" * 78)
    print("all checks passed" if not failures else f"{len(failures)} FAILED: {failures}")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
