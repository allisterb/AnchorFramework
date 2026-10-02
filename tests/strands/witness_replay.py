"""A counterexample, carried back into Dogwood's language and put to the real engine.

    python tests/strands/witness_replay.py

WHAT THIS PROTECTS. A finding here names a concrete value -- `gap = 960` -- and claims the engine
decides it one way while the property demanded the other. Every part of that sentence can be wrong
in a way that still reads perfectly:

    the session         built from the module's own recipe. Evaluate `Session(960)` wrongly and
                        the trace is a different history, judged correctly, reported as this one
    the DIRECTION       whether the claim demanded an allow or a refusal. Get it backwards and a
                        policy that is right is reported as broken, with engine output "proving" it
    the trace syntax    a malformed line the engine rejects is a loud failure and safe; a line the
                        engine ACCEPTS with different meaning is the dangerous one
    the alignment       which event's verdict answers the question, keyed on the timestamp

The direction is the one with no symptom, so it is asserted in both polarities, on two claims that
differ only in which way round they read.

THE ENGINE HALF NEEDS THE BUILT BINARY and skips without it -- but the reading half does not, and
that half is where the reasoning lives. Run it either way.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from checker.explain import Rec, Tag, parse, read, show_value  # noqa: E402
from checker.witness import (DOGWOOD, Unsupported, cedar_schema, confirm,  # noqa: E402
                             demanded, namespace_of, session, trace_text, violations)

EXAMPLES = REPO / "examples" / "aws1"
POLICIES = REPO / "tests" / "policies"

# TLC's own output shape, both of them. A single-variable state prints bare; a multi-variable one
# prints `/\` conjuncts. Recorded here rather than produced by a run, because what is being tested
# is the READING of it -- and a fixture makes the two shapes explicit instead of incidental.
ONE_VARIABLE = """\
Error: Invariant LosesWriteAfter10m is violated by the initial state:
Error: The behavior up to this point is:
State 1: <Initial predicate>
gap = 960

"""

TAGGED_RECORD = """\
Error: Invariant OutsideIsRefused is violated by the initial state:
State 1: <Initial predicate>
req = [port |-> [k |-> "n", v |-> 22], origin |-> [k |-> "s", v |-> "external"]]

"""

TWO_VARIABLES = """\
Error: Invariant Something is violated by the initial state:
State 1: <Initial predicate>
/\\ gap = 5
/\\ other = 7

"""

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    # --- reading TLC's counterexample ------------------------------------------------------------
    v = violations(ONE_VARIABLE)
    check("a single-variable counterexample is read", len(v) == 1 and v[0].state == {"gap": 960},
          str(v and v[0].state))
    check("and the invariant is named", bool(v) and v[0].invariant == "LosesWriteAfter10m")

    two = violations(TWO_VARIABLES)
    check("a multi-variable counterexample is read too",
          len(two) == 1 and two[0].state == {"gap": 5, "other": 7}, str(two and two[0].state))

    tagged = violations(TAGGED_RECORD)
    # The generated module tags every scalar, so TLC prints `[k |-> "n", v |-> 22]` and not `22`.
    # Reading that back as the tag rather than the value is what lets the session be rebuilt.
    check("tagged scalars are read back as values",
          bool(tagged) and tagged[0].state["req"] == Rec((("port", Tag("Num", 22)),
                                                          ("origin", Tag("Str", "external")))),
          str(tagged and show_value(tagged[0].state.get("req"))))

    # --- THE DIRECTION, both ways ----------------------------------------------------------------
    # TrustDecay.tla carries two claims that differ only in which way round they read, which is
    # exactly the pair that would catch an inverted reading.
    decay = read(EXAMPLES / "TrustDecay.tla")

    loses = demanded(decay, "LosesWriteAfter15m", violations(
        "Invariant LosesWriteAfter15m is violated by the initial state:\ngap = 960\n\n")[0])
    check("a claim that the policy must REFUSE is read as demanding a refusal",
          loses is not None and loses.allow is False, str(loses))

    keeps = demanded(decay, "KeepsWriteWhileAdvisorEngaged", violations(
        "Invariant KeepsWriteWhileAdvisorEngaged is violated by the initial state:\ngap = 1\n\n")[0])
    check("a claim that the policy must ALLOW is read as demanding an allow",
          keeps is not None and keeps.allow is True, str(keeps))

    # And the self-check: a state where the claim is NOT violated must produce no demand, because
    # this reader disagreeing with TLC about what a counterexample is means it has no business
    # saying what the claim wanted.
    wrong = demanded(decay, "LosesWriteAfter15m", violations(
        "Invariant LosesWriteAfter15m is violated by the initial state:\ngap = 1\n\n")[0])
    check("a state that does NOT break the claim yields no demand, not a guess",
          wrong is not None and bool(wrong.why), str(wrong))

    # --- the session, from the module's own recipe ------------------------------------------------
    got = session(decay, loses, violations(
        "Invariant LosesWriteAfter15m is violated by the initial state:\ngap = 960\n\n")[0])
    check("the session is rebuilt from the module", len(got.events) == 2, got.why)
    check("and the times are the module's arithmetic, in seconds",
          [e.get("time") for e in got.events] == [1, 961],
          str([e.get("time") for e in got.events]))
    check("the decided event is the one the module names",
          got.index == 2, str(got.index))

    # `Len(Session(w))` -- how a module says "the last event". Unreadable without the Sequences
    # operators, and the symptom was a silently missing witness rather than an error.
    gate = read(EXAMPLES / "TradeGate.tla")
    gv = violations('Invariant FreshPriceAloneIsNotEnough is violated by the initial state:\n'
                    'prereq = "freshPriceOnly"\n\n')[0]
    gd = session(gate, demanded(gate, "FreshPriceAloneIsNotEnough", gv), gv)
    check("an index written as Len(Session(w)) is worked out", gd.index == 2, gd.why)

    # --- Dogwood's own syntax ---------------------------------------------------------------------
    text = trace_text(got.events, "AgentCore")
    lines = text.strip().splitlines()
    check("one trace line per event", len(lines) == 2, text)
    check("the timestamps lead each line",
          lines[0].startswith("@1 ") and lines[1].startswith("@961 "), text)
    check("the policy's own namespace is used, not ours",
          'AgentCore::Action::"execute_trade"::request' in lines[1], lines[1])
    # A response carries an output and no request_context; a decision carries the reverse. Getting
    # this wrong produces a line the engine ACCEPTS and reads differently, which is the bad case.
    check("a response event carries an output and no request_context",
          "output: {" in lines[0] and "request_context" not in lines[0], lines[0])
    check("a decision event carries a request_context",
          "request_context(" in lines[1], lines[1])

    # A value the renderer cannot write must stop it, not be approximated.
    try:
        trace_text([Rec((("time", 1), ("action", "x"), ("kind", "request"),
                         ("input", Rec((("a", Tag("Addr", (10, 0, 0, 1))),))),
                         ("output", Rec(()))))], "AgentCore")
        check("a value with no Dogwood form is refused, not guessed", False, "it rendered one")
    except Unsupported:
        check("a value with no Dogwood form is refused, not guessed", True)

    # --- the generated schema ---------------------------------------------------------------------
    from translator import DEFAULT_MAX_WINDOW, parse_policies, parse_schema, vocabulary  # noqa: PLC0415
    from translator.agentcore import AGENTCORE_SCHEMA  # noqa: PLC0415

    policy = EXAMPLES / "agent-policy.dw"
    body = policy.read_text(encoding="utf-8")
    check("the namespace comes from the policy", namespace_of(body) == "AgentCore",
          namespace_of(body))

    # The article's policies as published bind `eventResource`, a field of AgentCore's event schema
    # and not of Dogwood's default -- so they are read under that schema's spelling.
    scope_fields = parse_schema(AGENTCORE_SCHEMA.read_text(encoding="utf-8"))["scope_fields"]
    vocab = vocabulary(parse_policies(body, "", DEFAULT_MAX_WINDOW, scope_fields), 2, 8)
    schema = cedar_schema(vocab, "AgentCore", gd.events)
    check("every action the policy names is declared",
          all(f'action "{a}"' in schema for a in vocab["actions"]), schema[:200])
    check("and a field the policy compares gets its type from the literals",
          "profile_id?: Long" in schema, schema)

    # --- end to end, against the engine ------------------------------------------------------------
    if not DOGWOOD.exists():
        print(f"\n  SKIPPED the engine half: no binary at {DOGWOOD.name}. Build it with\n"
              f"    cargo build --release --locked --manifest-path ext/dogwood/Cargo.toml")
    else:
        # The article's own policy and the article's own stated intent, disagreeing -- confirmed by
        # Amazon's engine rather than by us. If this stops holding, either the policy changed or
        # our reading of Dogwood drifted, and both are worth a failed test.
        checker_output = ("Error: Invariant LosesWriteAfter15m is violated by the initial state:\n"
                          "gap = 960\n\n")
        found = confirm(EXAMPLES / "07-trust-decay.dw", EXAMPLES / "TrustDecay.tla",
                        checker_output)
        check("the engine answers", len(found) == 1 and found[0].engine is not None,
              found and found[0].why)
        check("it ALLOWS the trade 16 minutes after the last interaction",
              bool(found) and found[0].engine == "allow", str(found and found[0].engine))
        check("which confirms the finding rather than contradicting it",
              bool(found) and found[0].agreed is True, str(found and found[0].agreed))
        check("and the verdict is the one for the DECIDED event",
              bool(found) and found[0].at == 961, str(found and found[0].at))

        # The other direction, on the same policy: the claim that the agent KEEPS write access
        # while the advisor is engaged is broken too, and the engine denies rather than allows.
        keeps_found = confirm(EXAMPLES / "07-trust-decay.dw", EXAMPLES / "TrustDecay.tla",
                              "Error: Invariant KeepsWriteWhileAdvisorEngaged is violated by the "
                              "initial state:\ngap = 1\n\n")
        check("and a claim broken the other way is confirmed by a DENY",
              len(keeps_found) == 1 and keeps_found[0].engine == "deny"
              and keeps_found[0].agreed is True,
              str(keeps_found and (keeps_found[0].engine, keeps_found[0].why)))

    # --- the evidence has to be RUNNABLE, not just printed --------------------------------------
    # A finding somebody cannot reproduce is a finding they have to take on trust, which is the
    # thing this whole file exists to avoid. So the kept directory must be self-contained and the
    # command in it must be the command that produced the verdict.
    if DOGWOOD.exists():
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory(prefix="anchor-witness-test-") as tmp:
            kept = Path(tmp) / "witness"
            found = confirm(EXAMPLES / "07-trust-decay.dw", EXAMPLES / "TrustDecay.tla",
                            "Error: Invariant LosesWriteAfter15m is violated by the initial "
                            "state:\ngap = 960\n\n", keep=kept)
            c = found[0]

            check("the policy is COPIED in, not referenced",
                  (kept / "07-trust-decay.dw").exists(),
                  "a directory pointing at a policy elsewhere stops being evidence when moved")
            check("the generated schema is kept", (kept / "generated.cedarschema").exists())
            check("the trace is kept", (kept / "LosesWriteAfter15m.log").exists())
            check("and a README explains how to re-run it", (kept / "README.md").exists())

            readme = (kept / "README.md").read_text(encoding="utf-8")
            check("the README carries the exact command", c.command in readme, c.command)

            # THE ONE THAT MATTERS. A README telling somebody to run something other than what
            # produced the verdict is worse than no README: they run it, get a different answer,
            # and the disagreement is ours. So run it, from where it says to, and compare.
            rerun = subprocess.run([str(DOGWOOD), *c.command.split()[1:]], cwd=kept,
                                   capture_output=True, text=True, timeout=120)
            check("the command in the README runs", rerun.returncode == 0,
                  (rerun.stdout + rerun.stderr)[-300:])
            check("and reproduces the verdict this finding claims",
                  f"@{c.at}" in rerun.stdout and c.engine.upper() in rerun.stdout,
                  f"claimed {c.engine} at t={c.at}, got: {rerun.stdout.strip()[:200]}")

    # --- the event schema travels with the counterexample ----------------------------------------
    # A universal pin changes what history a temporal predicate can see, so the same policy and the
    # same trace mean different things under different schemas. Replaying a witness found under a
    # pinned reading against the engine's default answers a question nobody asked -- confidently,
    # and with the reference implementation's authority behind it.
    from checker.witness import replay_args  # noqa: PLC0415

    check("the event schema reaches the engine when there is one",
          "--event-schema" in replay_args("p.dw", "t.log", "s.cedarschema", "deployed.dwschema"),
          str(replay_args("p.dw", "t.log", "s.cedarschema", "deployed.dwschema")))
    check("and is absent when there is not, rather than guessed at",
          "--event-schema" not in replay_args("p.dw", "t.log", "s.cedarschema", None))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("a counterexample is carried back into Dogwood, and the engine is asked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
