---------------------------- MODULE AgentCoreOneTimeWrong ----------------------------
\* A DELIBERATELY WRONG claim about tests/policies/agentcore/examples/06-one-time-approval.dw, AWS's
\* one-time-approval example as published: that the first disbursement after an approval is
\* refused. It is allowed, so the claim is BROKEN -- and `--witness` must carry the counterexample
\* back into Dogwood in AgentCore's terms (eventPrincipal/eventResource, a sessionId, the policy's own
\* gateway) and have the engine confirm it under agentcore.dwschema. A witness written in Dogwood's
\* default terms would be replayed against a different policy -- every gateway-scoped rule would
\* simply not apply -- and its "confirmation" would mean nothing.
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

Session(w) ==
    CASE w = "approved" -> << Ev("InsuranceAPI___approve_claim", "request", NoFields, NoFields, 0),
                              Ev("InsuranceAPI___approve_claim", "response", NoFields, NoFields, 1),
                              Ev("InsuranceAPI___disburse_payment", DecisionKind, NoFields, NoFields, 10) >>
      [] OTHER          -> << Ev("InsuranceAPI___disburse_payment", DecisionKind, NoFields, NoFields, 10) >>

Allowed(w) == D!Decide(Session(w), Policies, Len(Session(w)), AllValues)

VARIABLE w
Init == w \in {"approved", "none"}
Next == UNCHANGED w
Spec == Init /\ [][Next]_w

FirstDisbursementDenied == (w = "approved") => ~Allowed(w)

=============================================================================
