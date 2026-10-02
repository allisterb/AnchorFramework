---------------------------- MODULE EmptyTrajectory ----------------------------
\* What `agent-policy.dw` -- the article's policies 1-5 and 7, as published, deployed together --
\* is SUPPOSED to do with a trade attempted before anything else has happened in the session.
\*
\* The article's own tables answer it twice: policy 3's, "Never called ... DENY" (no market price),
\* and policy 5's, "$30,000 ... None ... DENY" (no approval). Policy 2's text adds that the trade
\* must match a profile the session looked up. So a trade from an EMPTY trajectory should be denied
\* at any amount.
\*
\* It is allowed. Cedar permits by positive match, so any one permit that matches grants, and two
\* of the article's permits match an empty trajectory: policy 4, the budget cap, whose condition
\* is that the quotes so far total under $60,000 -- zero does -- and policy 7, trust decay, which
\* permits whenever no advisor has interacted in 15 minutes. Either one opens the door the other
\* protections were written to keep shut.
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

\* A trade, and nothing before it. The fields are the ones the article's policies read: policy 2
\* the profile, policy 5 the cost.
Trade(c) == Ev("execute_trade", DecisionKind,
               [profile_id |-> Str("client-1"), cost |-> Num(c)], NoFields, 1)

\* Below policy 5's threshold, and above it -- the second is the table's "$30,000, None" row.
Amounts == {1000, 30000}

Allowed(c) == D!Decide(<< Trade(c) >>, Policies, 1, AllValues)

VARIABLE amount
Init == amount \in Amounts
Next == UNCHANGED amount
Spec == Init /\ [][Next]_amount

NoTradeFromAnEmptyTrajectory == ~Allowed(amount)

=============================================================================
